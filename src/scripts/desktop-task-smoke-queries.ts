/**
 * `--watch` desktop smoke yalnız masaüstü yürütme görevlerini izlemelidir.
 * Genel task feed'inde server-brain sohbetleri de bulunur; bunları seçmek
 * smoke'u gerçek bir placement arızası yokken kırmızıya çevirir.
 */
export function latestDesktopTaskIdQuery(): string {
  return [
    "select id::text from tasks",
    "where payload->'metadata'->'routeDecision'->'taskRoute'->>'operationalRoute' = 'desktop_runtime'",
    "order by created_at desc limit 1",
  ].join(" ");
}
