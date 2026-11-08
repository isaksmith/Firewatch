// Records the console's 3D spread preview playing the packet fire's first hour (about 12 s at 1x).
import { launch, startCapture, sleep } from "./capture.mjs";

const { browser, page } = await launch();
await page.goto("http://localhost:5173/", { waitUntil: "networkidle" });
await sleep(2500);
await page.getByText("3D VIEW").first().click();
await sleep(7000);
await page.getByRole("button", { name: /reset/i }).last().click();
await sleep(300);
const cap = await startCapture(page, "spread");
await sleep(16000);
await cap.stop();
await browser.close();
