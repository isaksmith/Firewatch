import type { AlertSummary } from '../api'

export type QueueTab = 'active' | 'escalate' | 'suppressed'

export function filterQueue(alerts: AlertSummary[], tab: QueueTab): AlertSummary[] {
  if (tab === 'escalate') return alerts.filter((a) => a.recommendation === 'escalate')
  if (tab === 'suppressed') return alerts.filter((a) => a.recommendation === 'monitor')
  return alerts.filter((a) => a.recommendation !== 'monitor')
}
