# 04 — 各平台金鑰申請步驟

這份文件教你拿到每個平台的金鑰。**不用一次全部做完**，建議的順序是：

1. Claude API（最簡單，5 分鐘）
2. 蝦皮（或直接跳過用 CSV）
3. Facebook 粉專（20 分鐘）
4. TikTok（20 分鐘）
5. Instagram（最麻煩，可以先跳過用手動發）

> **安全提醒**：下面拿到的所有金鑰都只填進你自己電腦上的 `.env` 檔案。
> 不要貼給任何人，不要貼在對話裡，不要上傳到網路。

---

## Claude API（產生文案）

**要多久**：5 分鐘 **費用**：約 NT$2~3 一支影片

1. 打開 https://console.anthropic.com
2. 註冊 / 登入
3. 左邊選單找到 **API Keys** → 點 **Create Key**
4. 隨便取個名字（例如 `蝦皮工具`）→ Create
5. 複製出現的那串 `sk-ant-...`（**只會顯示這一次，關掉就看不到了**）
6. 打開專案資料夾的 `.env` 檔案（用記事本開就行），找到這行：

   ```
   ANTHROPIC_API_KEY=
   ```

   把金鑰貼在等號後面，不要有空格：

   ```
   ANTHROPIC_API_KEY=sk-ant-你的金鑰
   ```

7. 存檔
8. 左邊選單的 **Billing** 儲值（最低 US$5，大約可以做 200 支影片）

**不想花這筆錢？** 不填也可以，工具會用內建的樣板文案，流程照跑，只是文案比較平淡。

---

## 蝦皮聯盟開放 API

**要多久**：申請後等審核 **費用**：免費

1. 登入你的蝦皮聯盟後台
2. 找「開放 API」或「Open API」相關的申請入口（位置各市場不同，找不到就寫信問客服）
3. 申請通過後會拿到 **App ID** 和 **App Secret**
4. 填進 `.env`：

   ```
   SHOPEE_APP_ID=你的AppID
   SHOPEE_APP_SECRET=你的AppSecret
   ```

5. 打開 `config.yaml`，把

   ```yaml
   source:
     mode: demo
   ```

   改成

   ```yaml
   source:
     mode: shopee
   ```

6. **先跑這個測試**，確認蝦皮到底給了你哪些欄位：

   ```bash
   python run.py test-shopee
   ```

   它會實際打一次 API，把回傳的原始欄位攤開給你看，然後直接告訴你
   「利潤、銷量、評分」這三個篩選條件有沒有資料可以用。

   **為什麼要多跑這一步**：蝦皮的 API 會改版，而且不同市場、不同權限等級
   回傳的欄位不一定一樣。如果它沒有給銷量或評分，你的篩選條件就會把
   所有商品都擋掉。先測一次，就不用猜。

7. 確認欄位沒問題後，執行 `python run.py pick` 看選出哪些商品

### 申請不到 / 還在審核？用 CSV 就好

這不是次等選擇，很多人長期都用這個方式，因為選品本來就該由人來判斷。

1. 複製 `products.example.csv` 成 `products.csv`
2. 用 Excel 或 Google 試算表打開，照欄位填入你的商品（欄位說明見 `02-你需要準備的資訊.md`）
3. 最重要的是 `affiliate_link` 欄要填**你自己的蝦皮分潤連結**
4. 存檔成 CSV（編碼選 UTF-8）
5. `config.yaml` 改成 `mode: csv`

> 填 30 件商品大約花 20~30 分鐘，可以讓工具自動做一個月的影片。

---

## Facebook 粉絲專頁

**要多久**：20 分鐘 **費用**：免費

### 前置條件

- [ ] 你有一個**粉絲專頁**（不是個人檔案）
- [ ] 你是那個粉專的管理員

還沒有粉專的話：Facebook → 左邊選單 → 專頁 → 建立新專頁。

### 步驟 A：建立 Meta 應用程式

1. 打開 https://developers.facebook.com
2. 右上角 **我的應用程式** → **建立應用程式**
3. 使用情境選 **其他** → 下一步
4. 應用程式類型選 **商業** → 下一步
5. 填應用程式名稱（例如 `蝦皮影片工具`）和聯絡信箱 → 建立
6. 進到應用程式後台，左邊選單 **應用程式設定 → 基本資料**
7. 記下 **應用程式編號**（App ID）和 **應用程式密鑰**（App Secret，要按「顯示」）

### 步驟 B：產生使用者權杖

1. 打開 https://developers.facebook.com/tools/explorer/
2. 右上角 **Meta App** 下拉選單，選你剛建立的應用程式
3. 下面 **Permissions** 欄位，逐一加入這些權限（打字會自動搜尋）：

   ```
   pages_show_list
   pages_read_engagement
   pages_manage_posts
   business_management
   ```

   如果之後也要發 IG，順便加這兩個：

   ```
   instagram_basic
   instagram_content_publish
   ```

4. 點 **Generate Access Token** → 跳出視窗登入並同意授權
5. 複製產生的那串權杖（很長）

   > 這個權杖只有 1~2 小時有效，所以下一步要馬上做。

### 步驟 C：用小幫手自動換成長期權杖

回到終端機，在專案資料夾執行：

```bash
python tools/meta_setup.py
```

它會問你三個東西（就是上面拿到的），然後自動完成：

- 把短期權杖換成長期權杖（約 60 天）
- 列出你所有粉專，並取得各自的粉專權杖
- 找出有連結 Instagram 商業帳號的粉專
- **直接印出你該貼進 `.env` 的內容**

把印出來的那幾行複製貼到 `.env` 就完成了。

### 步驟 D：啟用

打開 `config.yaml`，找到：

```yaml
  facebook:
    enabled: false
```

改成 `enabled: true`。

然後執行 `python run.py doctor` 確認全部打勾。

> **60 天後權杖會過期**，到時候重跑一次步驟 B + C 就好。
> 工具發佈失敗時會明確告訴你「存取權杖失效」，不會讓你猜。

---

## Instagram

**要多久**：30 分鐘以上 **費用**：免費（影片託管可能要一點點）

### 前置條件（缺一不可）

- [ ] IG 帳號已切換成**商業帳號**或**創作者帳號**
      （IG App → 設定 → 帳號類型和工具 → 切換為專業帳號）
- [ ] 該 IG 帳號已**連結到你的 Facebook 粉專**
      （IG App → 設定 → 帳號中心 → 新增 Facebook 帳號）
- [ ] 已完成上面 Facebook 的步驟，且權限有加 `instagram_basic` 和 `instagram_content_publish`

如果前置條件都做好了，`python tools/meta_setup.py` 就會自動印出 `IG_USER_ID` 和 `IG_ACCESS_TOKEN`。

### 最後一關：影片公開網址

**這是 Instagram 最麻煩的地方。** IG 的 API 不接受你上傳檔案，只接受一個「公開網址」，由 IG 自己去抓。

#### 做法一：Cloudflare Tunnel（免費，推薦）

1. 安裝 cloudflared：
   - Windows：`winget install Cloudflare.cloudflared`
   - Mac：`brew install cloudflared`

2. 每次要發佈之前，另外開一個終端機視窗執行：

   ```bash
   cd shopee-affiliate-bot
   python -m http.server 9000 --directory output
   ```

3. 再開第三個終端機視窗執行：

   ```bash
   cloudflared tunnel --url http://localhost:9000
   ```

4. 它會印出一個像 `https://xxxx-yyyy.trycloudflare.com` 的網址
5. 把那個網址填進 `config.yaml`：

   ```yaml
   instagram:
     video_url_base: https://xxxx-yyyy.trycloudflare.com
   ```

6. 執行 `python run.py approve all`

> 注意：這個網址每次重開都會變，所以每次發佈前都要更新 `config.yaml`。
> 而且發佈期間那兩個終端機視窗不能關掉。

#### 做法二：物件儲存（比較穩定，適合長期）

把 `output/` 資料夾同步到 Cloudflare R2、AWS S3、或任何你自己的網站空間，
然後把公開網址前綴填進 `video_url_base`。這個網址不會變，設定一次就好。

#### 做法三：IG 就用手動發（我的建議）

`config.yaml` 裡 `instagram.enabled` 保持 `false`，`manual.enabled` 設 `true`。

工具會把影片和文案都準備好放在 `output/待發佈/`，你用手機同步過去，
自己發到 IG。**IG 演算法不會因為你手動發而給比較差的觸及**，
而且手動發你可以順手更新限時動態和個人簡介的連結，轉換率通常更好。

---

## TikTok

**要多久**：20 分鐘 **費用**：免費

### 步驟 A：建立開發者應用程式

1. 打開 https://developers.tiktok.com
2. 用你的 TikTok 帳號登入
3. 右上角 **Manage apps** → **Connect an app**
4. 填應用程式名稱和說明 → 送出
5. 進到應用程式頁面，記下 **Client Key** 和 **Client Secret**

### 步驟 B：設定權限與回呼網址

1. 在應用程式頁面找到 **Add products**，加入 **Login Kit** 和 **Content Posting API**
2. 在 Login Kit 的設定裡，**Redirect URI** 填入（一個字都不能差）：

   ```
   http://localhost:8080/callback
   ```

3. 在 Scopes（權限範圍）勾選：
   - `user.info.basic`
   - `video.upload` ← 草稿模式需要這個
   - `video.publish` ← 直接公開發佈需要，但要通過審核才會給

4. 把你自己的 TikTok 帳號加進 **Target users / 測試使用者** 名單
   （應用程式還沒上架前，只有名單內的帳號能授權）

### 步驟 C：用小幫手完成授權

回到終端機執行：

```bash
python tools/tiktok_auth.py
```

程式會：
1. 問你 Client Key 和 Client Secret
2. 自動打開瀏覽器帶你到 TikTok 授權頁 → **你只要點「同意授權」**
3. 自動接住授權碼、換成權杖
4. 印出你該貼進 `.env` 的三行

把那三行貼到 `.env`，然後在 `config.yaml` 把 `tiktok.enabled` 改成 `true`。

### 草稿模式 vs 直接發佈

`config.yaml` 裡的 `tiktok.mode`：

| 模式 | 需要審核 | 行為 |
|---|---|---|
| `draft`（預設） | ❌ 不用 | 影片送到 TikTok App 草稿匣，你點一下就能發，文案存在 `output/待發佈/` |
| `direct` | ✅ 要 | 直接發佈。沒通過審核的話影片只會是「僅自己可見」 |

**建議先用 `draft`。** 它不需要任何審核，而且你在發佈前還能看一眼影片，多一層保險。

想申請 `direct` 的話，要在 TikTok 開發者後台送出 Content Posting API 的審核申請，
審核會看你的應用程式用途說明和隱私權政策網址。

---

## 全部設定完的檢查

```bash
python run.py doctor
```

每一項都是 ✅ 就可以開始了。有 ❌ 的話，它會直接告訴你缺哪個、去哪裡補。

---

## 下一步

讀 [`05-每日操作與自動排程.md`](05-每日操作與自動排程.md)，設定成每天自動跑。
