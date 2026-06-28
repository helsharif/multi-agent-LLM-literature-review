const { exec } = require("node:child_process");

const url = process.env.APP_URL || "http://localhost:3000";
const timeoutMs = Number(process.env.OPEN_BROWSER_TIMEOUT_MS || 60000);
const startedAt = Date.now();

function openUrl(target) {
  const platform = process.platform;
  const command =
    platform === "win32"
      ? `start "" "${target}"`
      : platform === "darwin"
        ? `open "${target}"`
        : `xdg-open "${target}"`;

  exec(command, (error) => {
    if (error) {
      console.error(`Could not open browser: ${error.message}`);
      process.exit(1);
    }
    console.log(`Opened ${target}`);
    process.exit(0);
  });
}

async function waitForServer() {
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url, { method: "HEAD" });
      if (response.ok || response.status < 500) {
        openUrl(url);
        return;
      }
    } catch {
      // Server is not ready yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

  console.error(`Timed out waiting for ${url}`);
  process.exit(1);
}

waitForServer();
