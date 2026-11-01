import { chromium, expect, test, type BrowserContext } from "@playwright/test";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const EXTENSION_DIST_PATH = path.resolve(__dirname, "../../.output/chrome-mv3");

// Ảnh PNG 1x1 hợp lệ dùng để vẽ lên canvas tạo ảnh lớn trong trang đọc truyện mẫu
const TINY_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

interface CapturedTranslateCall {
  authorization: string;
  langPair: string;
  idempotencyKey: string;
}

test.describe("Phase 3 Chrome Extension E2E (Local Mock Reader + Mock Server)", () => {
  let server: http.Server;
  let serverUrl = "";
  let context: BrowserContext;
  let extensionId = "";

  const translateCalls: CapturedTranslateCall[] = [];
  let tokenRefreshCalls = 0;

  test.beforeAll(async () => {
    if (!fs.existsSync(EXTENSION_DIST_PATH)) {
      throw new Error(
        `Chưa tìm thấy bản build tại ${EXTENSION_DIST_PATH}. Hãy chạy "npm run build" trước khi chạy test:e2e.`
      );
    }

    server = http.createServer((req, res) => {
      const reqUrl = new URL(req.url || "/", "http://127.0.0.1");

      // 1. Phục vụ ảnh mẫu PNG
      if (reqUrl.pathname === "/sample-page.png") {
        const buf = Buffer.from(TINY_PNG_BASE64, "base64");
        res.writeHead(200, {
          "Content-Type": "image/png",
          "Access-Control-Allow-Origin": "*",
        });
        res.end(buf);
        return;
      }

      // 2. Trang HTML mô phỏng Reader (lazy-load data-src + blob: + ảnh webtoon cao)
      if (reqUrl.pathname === "/reader") {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(`<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8" />
  <title>Mock Comic Reader</title>
  <style>
    body { margin: 0; padding: 20px; background: #111827; color: #fff; }
    .comic-contain { max-width: 800px; margin: 0 auto; }
    img.comic-page { width: 500px; height: 750px; display: block; margin-bottom: 24px; background: #fff; }
  </style>
</head>
<body>
  <div class="comic-contain" id="reader-root">
    <!-- Ảnh 1: Lazy-load qua data-src, hiển thị co giãn CSS 500x750 trên kích thước gốc 1000x1500 -->
    <img
      id="lazy-comic-img"
      class="comic-page"
      width="1000"
      height="1500"
      data-src="${serverUrl}/sample-page.png"
      alt="Page 1"
    />
    <!-- Ảnh 2: Ảnh blob: tạo động trong trang -->
    <img
      id="blob-comic-img"
      class="comic-page"
      width="800"
      height="2400"
      alt="Page 2 Tall Webtoon"
    />
  </div>
  <script>
    // Khởi tạo ảnh blob: kích thước 800x2400
    const canvas = document.createElement('canvas');
    canvas.width = 800;
    canvas.height = 2400;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, 800, 2400);
    canvas.toBlob((blob) => {
      if (blob) {
        const url = URL.createObjectURL(blob);
        document.getElementById('blob-comic-img').src = url;
      }
    }, 'image/png');
  </script>
</body>
</html>`);
        return;
      }

      // 3. Endpoint làm mới token khi gặp 401
      if (req.method === "POST" && reqUrl.pathname === "/auth/v1/token") {
        let rawBody = "";
        req.on("data", (chunk) => {
          rawBody += chunk.toString();
        });
        req.on("end", () => {
          tokenRefreshCalls += 1;
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(
            JSON.stringify({
              access_token: "refreshed_valid_token_999",
              refresh_token: "refresh_tok_123",
            })
          );
        });
        return;
      }

      // 4. Endpoint dịch trang truyện POST /api/v1/page/translate
      if (req.method === "POST" && reqUrl.pathname === "/api/v1/page/translate") {
        const authHeader = String(req.headers["authorization"] || "");
        const chunks: Buffer[] = [];
        req.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
        req.on("end", () => {
          const bodyStr = Buffer.concat(chunks).toString("utf-8");
          const langMatch = bodyStr.match(/name="lang_pair"\r\n\r\n([^\r\n]+)/);
          const idemMatch = bodyStr.match(
            /name="idempotency_key"\r\n\r\n([^\r\n]+)/
          );

          translateCalls.push({
            authorization: authHeader,
            langPair: langMatch ? langMatch[1] : "",
            idempotencyKey: idemMatch ? idemMatch[1] : "",
          });

          // Nếu token đang là token hết hạn -> trả 401 để kiểm tra luồng tự động refresh token
          if (authHeader === "Bearer expired_token_401") {
            res.writeHead(401, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ detail: "Token đã hết hạn" }));
            return;
          }

          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(
            JSON.stringify({
              blocks: [
                {
                  id: 0,
                  bbox: [100, 150, 500, 350],
                  source_text: "你敢拦我？！",
                  translation: "Ngươi dám cản ta sao?!",
                },
              ],
              lang_pair: langMatch ? langMatch[1] : "zh-vi",
              cached: false,
              credits: {
                subscription: 0,
                one_time: 18,
                total: 18,
              },
            })
          );
        });
        return;
      }

      res.writeHead(404);
      res.end("Not found");
    });

    await new Promise<void>((resolve) => {
      server.listen(0, "127.0.0.1", () => resolve());
    });
    const addr = server.address();
    const port = typeof addr === "object" && addr ? addr.port : 0;
    serverUrl = `http://127.0.0.1:${port}`;

    const userDataDir = fs.mkdtempSync(path.join(path.dirname(__dirname), "pw-profile-"));
    context = await chromium.launchPersistentContext(userDataDir, {
      headless: false,
      args: [
        `--disable-extensions-except=${EXTENSION_DIST_PATH}`,
        `--load-extension=${EXTENSION_DIST_PATH}`,
        "--no-sandbox",
      ],
    });

    let [sw] = context.serviceWorkers();
    if (!sw) {
      sw = await context.waitForEvent("serviceworker");
    }
    extensionId = sw.url().split("/")[2];
  });

  test.afterAll(async () => {
    if (context) {
      await context.close();
    }
    if (server) {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  test("1. Hover hiện nút Dịch, gọi qua background kèm Bearer token, tự refresh khi gặp 401, vẽ đúng tọa độ và bật/tắt Xem bản gốc", async () => {
    // Cấu hình serverUrl + expired_token_401 + refresh_token qua Popup để kiểm chứng cả luồng 401 -> refresh -> 200
    const popupPage = await context.newPage();
    await popupPage.goto(
      `chrome-extension://${extensionId}/popup.html?tabUrl=${encodeURIComponent(
        `${serverUrl}/reader?site=baozimh`
      )}`
    );
    await popupPage.fill("#input-server-url", serverUrl);
    await popupPage.fill("#input-access-token", "expired_token_401");
    await popupPage.fill("#input-refresh-token", "refresh_tok_123");
    await popupPage.click('[data-testid="btn-save-config"]');
    await popupPage.close();

    const readerPage = await context.newPage();
    await readerPage.goto(`${serverUrl}/reader?site=baozimh`);

    const firstStage = readerPage.locator('[data-testid="ctvn-image-stage"]').first();
    await expect(firstStage).toBeVisible();

    // Rê chuột vào ảnh để hiện nút "Dịch trang này"
    await firstStage.hover();
    const translateBtn = firstStage.locator('[data-testid="ctvn-btn-translate-page"]');
    await expect(translateBtn).toBeVisible();
    await expect(translateBtn).toHaveText("Dịch trang này");

    // Click dịch trang
    await translateBtn.click();

    // Chờ lớp phủ bong bóng thoại tiếng Việt xuất hiện
    const translatedBlock = firstStage.locator('[data-testid="ctvn-translated-block"]');
    await expect(translatedBlock).toBeVisible({ timeout: 10_000 });
    await expect(translatedBlock).toContainText("Ngươi dám cản ta sao?!");

    // Kiểm chứng background đã gặp 401 với expired_token_401, tự động gọi /auth/v1/token và thử lại với refreshed_valid_token_999
    expect(tokenRefreshCalls).toBe(1);
    expect(translateCalls.length).toBe(2);
    expect(translateCalls[0].authorization).toBe("Bearer expired_token_401");
    expect(translateCalls[1].authorization).toBe("Bearer refreshed_valid_token_999");
    expect(translateCalls[1].langPair).toBe("zh-vi");

    // Kiểm chứng nút bật/tắt "Xem bản gốc / Xem bản dịch" hoạt động
    const toggleBtn = firstStage.locator('[data-testid="ctvn-btn-toggle-page"]');
    await expect(toggleBtn).toBeVisible();
    await toggleBtn.click();
    await expect(translatedBlock).toBeHidden();

    await toggleBtn.click();
    await expect(translatedBlock).toBeVisible();

    await readerPage.close();
  });

  test("2. Mở Popup trên trang web lạ hiển thị rõ 'Trang web chưa được hỗ trợ'", async () => {
    const popupPage = await context.newPage();
    await popupPage.goto(
      `chrome-extension://${extensionId}/popup.html?tabUrl=${encodeURIComponent(
        "https://unknown-manga-site.example.com/chapter-1"
      )}`
    );

    const banner = popupPage.locator('[data-testid="unsupported-banner"]');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Trang web chưa được hỗ trợ");
    await popupPage.close();
  });
});
