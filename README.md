# Medical Journal Daily Agent

每日自動追蹤醫學期刊新文獻的 agent:抓取期刊 RSS、以 Crossref/PubMed 補齊 DOI 與 PMID、用 LLM(Gemini/OpenAI/Claude)將 Abstract 完整翻譯成繁體中文、產生 Markdown 報告,並透過 GitHub Actions 每日排程推送到 Telegram。

原始版本以神經科期刊為例(Neurology、JAMA Neurology、NEJM Neurology/Neurosurgery、The Lancet Neurology、Nature Reviews Neurology、Annals of Neurology、The Lancet、Stroke),**其他科別只需更換 RSS 來源即可套用**,見下方〈改成你的科別〉。

## 運作方式

```
期刊 RSS ──► 文章頁 / Crossref 補 metadata(DOI、abstract、PDF URL)
                │
                ▼
          PubMed 查 PMID
                │
                ▼
     LLM 翻譯 Abstract 成繁體中文
                │
                ▼
   reports/YYYY-MM-DD-<journal>-daily.md
                │
                ▼
        Telegram 純文字推送(每篇一則,URL 可點)
```

- 已處理過的文章記錄在 `.neurology_agent_state.json`,不會重複翻譯。
- GitHub Actions 每天 02:00 UTC(台北 10:00)自動執行,報告 commit 回 repo。

## 快速開始(GitHub Actions 全自動)

1. **Fork 這個 repo**(或 Use this template)。
2. 建一個 Telegram bot:找 [@BotFather](https://t.me/BotFather) → `/newbot` 取得 token;先傳一則訊息給你的 bot,再開 `https://api.telegram.org/bot<token>/getUpdates` 讀出 `chat.id`。
3. 在 repo 的 **Settings → Secrets and variables → Actions** 加入 Secrets:

   | Secret | 說明 |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | BotFather 給的 token |
   | `TELEGRAM_CHAT_ID` | 你的 chat id |
   | `GEMINI_API_KEY` | 預設 LLM provider(免費額度即夠用) |
   | `NCBI_EMAIL` | 你的 email,PubMed API 禮貌性要求 |

   選用 Variables:`LLM_PROVIDER`(`gemini`/`openai`/`claude`,預設 `gemini`)、`LLM_MODEL`。用 OpenAI 或 Claude 時改設 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`。
4. 到 **Actions** 頁面啟用 workflow,選 **Daily neurology digest → Run workflow** 手動跑一次驗證。
5. 之後每天台北時間 10:00 自動執行。

## 本地執行

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cat > .env <<'ENV'
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
NCBI_EMAIL=you@example.com
ENV

# 單一期刊
python -m neurology_agent run --journal neurology --since 24h

# 全部期刊
python -m neurology_agent run-all --since 24h

# 推送到 Telegram
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python scripts/send_telegram.py
```

常用參數:`--since`(`24h`、`7d`、`all`、`last-run`)、`--limit`(每次最多處理篇數,預設 20)、`--no-pdf`(不下載 PDF)、`--no-state`(不記錄已處理狀態)。

## 改成你的科別

大多數期刊(Wiley、Elsevier/Lancet 系、Nature 系、AHA 系)走通用路徑,只需三步:

1. **`neurology_agent/sources.py`**:在檔案開頭仿照現有常數加上你的期刊 RSS URL,並仿照 `discover_lancet_neurology_articles` 加一個小 wrapper(呼叫通用的 `discover_feed_articles(client, FEED_URL, "期刊名", HOME_URL, ...)`)。

   各家 RSS 位置範例:
   - Wiley 系:`https://onlinelibrary.wiley.com/action/showFeed?jc=<journal-code>&type=etoc&feed=rss`
   - Lancet 系:`https://www.thelancet.com/rssfeed/<code>_current.xml`
   - Nature 系:`https://www.nature.com/<code>.rss`
   - AHA 系:`https://www.ahajournals.org/action/showFeed?jc=<code>&type=etoc&feed=rss`
   - JAMA 系:期刊網頁下方的 RSS 連結

2. **`neurology_agent/cli.py`**:把期刊 slug 加進 `JOURNALS`,並在 `run()` 的分支中把它導向 `enrich_publisher_article` 那一組。

3. **`neurology_agent/report.py`**:在 `labels` dict 加上 slug 與顯示名稱。

不需要的期刊直接從 `cli.py` 的 `JOURNALS` 移除即可。

## 注意事項

- 報告含期刊 Abstract 的翻譯,供**個人學術追蹤**使用;若你的 fork 設為公開,請自行評估是否適合公開這些內容(可將 fork 設為 private,Actions 免費額度仍適用)。
- PDF 下載只在來源回傳真正的 `%PDF` bytes 時存檔;GitHub Actions 環境通常會被出版社防護擋住,workflow 預設 `--no-pdf`。
- Actions 排程在整點附近可能延遲數分鐘至數十分鐘,屬 GitHub 正常現象。

## License

MIT
