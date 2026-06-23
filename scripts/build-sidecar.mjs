// Build the Python sidecar into a one-file executable and place it where Tauri
// expects an externalBin: src-tauri/binaries/savepoint-sidecar-<target-triple><ext>.
// Run as part of the release build (see tauri.conf.json beforeBuildCommand).
import { execSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const triple = execSync("rustc -vV").toString().match(/host:\s*(\S+)/)?.[1];
if (!triple) {
  console.error("could not determine Rust target triple from `rustc -vV`");
  process.exit(1);
}

// A running sidecar locks the .exe, so PyInstaller can't overwrite it
// (PermissionError / Access denied). Kill stale instances first.
try {
  if (process.platform === "win32") {
    execSync("taskkill /IM savepoint-sidecar.exe /F /T", { stdio: "ignore" });
  } else {
    execSync("pkill -f savepoint-sidecar", { stdio: "ignore" });
  }
} catch {
  // none running — fine
}

console.log("Building sidecar with PyInstaller…");
execSync("uv run pyinstaller savepoint-sidecar.spec --noconfirm --clean", {
  cwd: "sidecar",
  stdio: "inherit",
});

const ext = process.platform === "win32" ? ".exe" : "";
const src = join("sidecar", "dist", `savepoint-sidecar${ext}`);
const outDir = join("src-tauri", "binaries");
mkdirSync(outDir, { recursive: true });
const dest = join(outDir, `savepoint-sidecar-${triple}${ext}`);
copyFileSync(src, dest);
console.log(`Placed sidecar → ${dest}`);
