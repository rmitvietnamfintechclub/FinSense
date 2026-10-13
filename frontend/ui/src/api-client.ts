const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

export const ADMIN_TOKEN_KEY = 'admin_token';

// Carries the status so callers branch on it, not on message text — the message is the
// API's human-readable detail and can say anything.
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function apiClient<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = typeof window !== 'undefined' ? localStorage.getItem(ADMIN_TOKEN_KEY) : null;

  const headers = new Headers(options.headers);
  headers.set('Content-Type', 'application/json');
  // Sent on public calls too; those endpoints ignore it.
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${endpoint}`, { ...options, headers });

  // A 401 only means "session over" when we sent a token. Without one it's a failed
  // login, and the caller needs the API's detail ("Invalid credentials"), not a redirect.
  if (response.status === 401 && token) {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
    if (window.location.pathname !== '/admin/login') {
      // Full load, not router.push: resets every component's view of the login state.
      window.location.assign('/admin/login');
    }
    throw new ApiError('Session expired', 401);
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    // FastAPI's 422 sends detail as a list of field errors; only a string is display-ready.
    const detail = typeof errorData.detail === 'string' ? errorData.detail : null;
    throw new ApiError(detail || `API Error: ${response.status}`, response.status);
  }

  return response.json() as Promise<T>;
}
