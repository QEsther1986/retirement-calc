"""用 Claude 產生短影音腳本 + 貼文文案。

設計重點：
  1. 用「結構化輸出」(output_config.format) 強制回傳固定格式的 JSON，
     這樣程式可以穩定解析，不會因為 AI 多寫一句話就壞掉。
  2. 內建合規護欄：不准編造療效、不准保證效果、必須標示合作聲明。
     這不是為了囉唆 — 誇大不實的商品文案在台灣可能違反公平交易法，
     而且會讓你的社群帳號被檢舉下架。
  3. 沒有設定 ANTHROPIC_API_KEY 時，自動改用內建的樣板寫法，
     讓你在還沒申請 API 金鑰前也能把流程跑完。
"""

from __future__ import annotations

import json

from .config import Config
from .logging_setup import get_logger
from .models import Product, ScriptSegment, VideoScript

log = get_logger(__name__)

# 回傳格式定義。additionalProperties: false 讓模型不能亂加欄位。
SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {
            "type": "string",
            "description": "影片前 3 秒的開場鉤子，12~22 個中文字，要讓人停下來",
        },
        "segments": {
            "type": "array",
            "minItems": 3,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "這一段的旁白，15~30 個中文字，口語、像跟朋友講話",
                    },
                    "on_screen": {
                        "type": "string",
                        "description": "畫面上的大字重點，6~12 個中文字",
                    },
                },
                "required": ["text", "on_screen"],
                "additionalProperties": False,
            },
        },
        "cta": {
            "type": "string",
            "description": "結尾行動呼籲，15~25 個中文字，引導看留言/簡介的連結",
        },
        "caption": {
            "type": "string",
            "description": "社群貼文文案，60~140 字，開頭要吸睛，結尾含合作聲明",
        },
        "hashtags": {
            "type": "array",
            "minItems": 5,
            "maxItems": 12,
            "items": {"type": "string", "description": "不含 # 符號的標籤文字"},
        },
    },
    "required": ["hook", "segments", "cta", "caption", "hashtags"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """你是台灣短影音帶貨腳本寫手，專門寫 15~30 秒的直式短影音（Reels / Shorts / TikTok）。

寫作風格：
- 繁體中文，台灣用語（例如「超值」「CP值」「回購」，不要用「性价比」「视频」等中國用語）
- 口語、像跟朋友聊天，不要像廣告稿
- 前 3 秒一定要有具體的鉤子：一個痛點、一個反差、或一個數字
- 每句話短，適合配音朗讀，不要有難念的詞

嚴格禁止（違反會讓使用者的帳號被檢舉、甚至觸法）：
- 不可以編造商品沒有提供的規格、成分、功效
- 不可以宣稱療效（治療、改善疾病、減肥瘦身效果）
- 不可以用「最」「第一」「保證」「100%」這類絕對化用語
- 不可以捏造「我用了三個月」這種你沒有的親身經歷
- 不確定的事就不要講，只根據提供的商品資料寫

貼文文案結尾必須包含這句合作聲明（一字不改）：本影片含蝦皮分潤連結，購買不影響您的價格。"""


def _fallback_script(product: Product) -> VideoScript:
    """沒有 Claude API 金鑰時使用的樣板腳本。品質普通，但流程能跑。"""
    log.warning("沒有偵測到 ANTHROPIC_API_KEY，改用內建樣板腳本（品質較一般）。")
    price = f"{product.price:,.0f}"
    segments = [
        ScriptSegment(text=f"最近很多人問我{product.name}到底值不值得買。",
                      on_screen="值得買嗎？"),
        ScriptSegment(text=f"這款目前是 {price} 元，累積銷量已經超過 {product.sales:,} 件。",
                      on_screen=f"NT${price}"),
        ScriptSegment(text=f"買家平均給了 {product.rating:.1f} 顆星，評價算是穩定的。",
                      on_screen=f"評分 {product.rating:.1f}★"),
        ScriptSegment(text="有需要的人可以自己看看詳細規格再決定。",
                      on_screen="連結在留言"),
    ]
    return VideoScript(
        hook=f"{product.name}，現在這個價格合理嗎？",
        segments=segments,
        caption=(
            f"{product.name}\n"
            f"目前售價 NT${price}，銷量 {product.sales:,} 件，評分 {product.rating:.1f} 星。\n"
            f"有興趣的可以點連結看詳細規格。\n\n"
            f"本影片含蝦皮分潤連結，購買不影響您的價格。"
        ),
        hashtags=["蝦皮", "蝦皮好物", "開箱", "好物推薦", "省錢", "團購"],
        cta="想看完整規格的，連結放留言區了。",
    )


class ScriptWriter:
    def __init__(self, config: Config):
        self.config = config
        self.model = config.get("content.model", "claude-opus-5")
        self.effort = config.get("content.effort", "medium")
        self.tone = config.get("content.tone", "親切、實在、不誇大")
        self.target_seconds = int(config.get("content.target_seconds", 25))
        self.audience = config.get("content.audience", "25~45 歲、會在蝦皮比價的台灣消費者")
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.config.has_secret("ANTHROPIC_API_KEY"):
            return None
        try:
            import anthropic
        except ImportError:
            log.warning("找不到 anthropic 套件，請執行 pip install -r requirements.txt")
            return None
        self._client = anthropic.Anthropic(api_key=self.config.secret("ANTHROPIC_API_KEY"))
        return self._client

    def _build_prompt(self, product: Product) -> str:
        facts = [
            f"商品名稱：{product.name}",
            f"售價：NT${product.price:,.0f}",
            f"累積銷量：{product.sales:,} 件",
            f"買家評分：{product.rating:.1f} / 5",
        ]
        if product.discount_rate > 0:
            facts.append(f"折扣幅度：約 {product.discount_rate * 100:.0f}% off")
        if product.shop_name:
            facts.append(f"賣場：{product.shop_name}")
        if product.category:
            facts.append(f"分類：{product.category}")

        return (
            "請依照下面這件商品的「真實資料」，寫一支短影音腳本。\n"
            "只能使用下列資料，不可以自行補充任何規格或功效。\n\n"
            + "\n".join(facts)
            + f"\n\n影片長度目標：約 {self.target_seconds} 秒（旁白總字數約 "
            f"{self.target_seconds * 5} 字上下）\n"
            f"目標觀眾：{self.audience}\n"
            f"語氣：{self.tone}\n"
        )

    def write(self, product: Product) -> VideoScript:
        client = self._get_client()
        if client is None:
            return _fallback_script(product)

        import anthropic

        log.info("正在用 %s 撰寫腳本：%s", self.model, product.name)
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": self._build_prompt(product)}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": SCRIPT_SCHEMA},
                },
            )
        except anthropic.AuthenticationError:
            log.error("ANTHROPIC_API_KEY 無效，改用樣板腳本。請到 console.anthropic.com 確認金鑰。")
            return _fallback_script(product)
        except anthropic.RateLimitError:
            log.error("Claude API 被限流了，改用樣板腳本。稍後再試或降低每天的影片數量。")
            return _fallback_script(product)
        except anthropic.APIStatusError as exc:
            log.error("Claude API 回應錯誤（%s），改用樣板腳本：%s", exc.status_code, exc.message)
            return _fallback_script(product)
        except anthropic.APIConnectionError:
            log.error("連不上 Claude API（網路問題），改用樣板腳本。")
            return _fallback_script(product)

        if response.stop_reason == "refusal":
            reason = getattr(response.stop_details, "explanation", "") if response.stop_details else ""
            log.error("Claude 拒絕產生這則內容（%s），改用樣板腳本。", reason or "未提供原因")
            return _fallback_script(product)

        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text:
            log.error("Claude 沒有回傳文字內容，改用樣板腳本。")
            return _fallback_script(product)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.error("Claude 回傳的內容不是合法 JSON，改用樣板腳本。")
            return _fallback_script(product)

        segments = [
            ScriptSegment(text=str(s.get("text", "")).strip(),
                          on_screen=str(s.get("on_screen", "")).strip())
            for s in data.get("segments", [])
            if str(s.get("text", "")).strip()
        ]
        if not segments:
            log.error("Claude 回傳的腳本沒有任何段落，改用樣板腳本。")
            return _fallback_script(product)

        script = VideoScript(
            hook=str(data.get("hook", "")).strip(),
            segments=segments,
            caption=str(data.get("caption", "")).strip(),
            hashtags=[str(h).lstrip("#").strip() for h in data.get("hashtags", []) if str(h).strip()],
            cta=str(data.get("cta", "")).strip(),
        )
        log.info("腳本完成：%d 段、旁白約 %d 字。",
                 len(script.segments), len(script.full_narration()))
        return script
