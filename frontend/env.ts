import { existsSync, readFileSync } from "fs";
import path from "path";

let loadedRootEnv = false;

export function loadRootEnv(): void {
  if (loadedRootEnv) return;
  loadedRootEnv = true;

  const envPath = path.resolve(process.cwd(), "..", ".env");
  if (!existsSync(envPath)) return;

  const lines = readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;

    const idx = line.indexOf("=");
    const key = line.slice(0, idx).trim();
    let value = line.slice(idx + 1).trim();
    if (!key || process.env[key] !== undefined) continue;

    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
  }
}

export function requireEnv(name: string): string {
  loadRootEnv();
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is not configured; set it in ../.env`);
  }
  return value;
}
