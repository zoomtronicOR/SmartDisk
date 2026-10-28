/** Podaci o računaru i pregledaču za audit prijave. Bez ličnih podataka i tajni; samo ono što pregledač izlaže. */
type UAData = {
  mobile?: boolean;
  platform?: string;
  getHighEntropyValues?: (hints: string[]) => Promise<Record<string, unknown>>;
};

export async function collectClientInfo(): Promise<Record<string, unknown>> {
  const nav = navigator as Navigator & { userAgentData?: UAData; deviceMemory?: number };
  const info: Record<string, unknown> = {
    screen: `${screen.width}x${screen.height}`,
    pixel_ratio: window.devicePixelRatio,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    color_depth: screen.colorDepth,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    language: navigator.language,
    languages: (navigator.languages ?? []).join(", "),
    cores: navigator.hardwareConcurrency,
    memory_gb: nav.deviceMemory,
    touch_points: navigator.maxTouchPoints,
    color_scheme: window.matchMedia("(prefers-color-scheme: dark)").matches ? "tamna" : "svetla",
    cookies: navigator.cookieEnabled,
    online: navigator.onLine,
  };
  // Client Hints (Chrome, Edge): tačna verzija OS-a (npr. razlikuje Windows 10 i 11), arhitektura, model.
  const ua = nav.userAgentData;
  if (ua) {
    info.mobile = ua.mobile;
    info.platform = ua.platform;
    try {
      const hi = (await ua.getHighEntropyValues?.(["platformVersion", "architecture", "bitness", "model", "fullVersionList"])) ?? {};
      info.platform_version = hi.platformVersion;
      info.architecture = hi.architecture;
      info.bitness = hi.bitness;
      info.model = hi.model || undefined;
      const brands = (hi.fullVersionList as { brand: string; version: string }[] | undefined) ?? [];
      const main = brands.find((b) => !/Not.?A.?Brand|Chromium/i.test(b.brand)) ?? brands[0];
      if (main) info.browser_full = `${main.brand} ${main.version}`;
    } catch {
      /* pregledač ne dozvoljava detaljne podatke - šalje se ono što postoji */
    }
  }
  return info;
}
