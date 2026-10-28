export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function csrfToken(): string {
  const entry = document.cookie.split("; ").find((c) => c.startsWith("sd_csrf="));
  return entry ? decodeURIComponent(entry.slice("sd_csrf=".length)) : "";
}

type Options = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  /** Pozadinsko osvežavanje: ne produžava sesiju na serveru. */
  background?: boolean;
};

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  if (options.background) headers["X-Background"] = "1";

  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "Server nije dostupan. Proverite mrežnu vezu.");
  }

  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message = typeof data?.detail === "string" ? data.detail : `Greška servera (${response.status}).`;
    if (response.status === 401 && path !== "/me" && path !== "/auth/login") {
      window.dispatchEvent(new Event("sd:unauthorized"));
    }
    throw new ApiError(response.status, message);
  }
  return data as T;
}
