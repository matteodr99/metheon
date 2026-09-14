/** "2 h ago", "just now", "3 d ago": for a card, not a log. */
export function timeAgo(iso: string, now: Date = new Date()): string {
  // The API writes naive UTC without a zone; tell the parser so.
  const then = new Date(/[Zz]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000)
  if (Number.isNaN(seconds)) {
    return ''
  }
  if (seconds < 60) {
    return 'just now'
  }
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) {
    return `${minutes} min ago`
  }
  const hours = Math.round(minutes / 60)
  if (hours < 48) {
    return `${hours} h ago`
  }
  const days = Math.round(hours / 24)
  return `${days} d ago`
}
