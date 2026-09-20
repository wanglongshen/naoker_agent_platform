export function resolveAvatarUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (/^https?:\/\//.test(url)) return url;
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
  return `${base}${url}`;
}
