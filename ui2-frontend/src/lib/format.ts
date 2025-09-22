export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return '0 B'
  const units = ['B','KB','MB','GB','TB','PB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  const value = (n < 10 && i > 0) ? n.toFixed(1) : Math.round(n).toString()
  return `${value} ${units[i]}`
}


