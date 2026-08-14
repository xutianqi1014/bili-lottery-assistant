export function connectEvents(onEvent: (name: string, data: unknown) => void): EventSource {
  const source = new EventSource("/api/events");
  [
    "job.started",
    "job.finished",
    "job.cancelled",
    "job.failed",
    "discovery.progress",
    "discovery.article_checked",
    "discovery.ready",
    "discovery.failed",
    "discovery.plan_skipped",
    "discovery.plan_failed",
    "run.plan_created",
    "run.confirmed",
    "run.started",
    "run.item_started",
    "run.item_updated",
    "run.source_closure_started",
    "run.source_closure_updated",
    "run.interrupted",
    "run.waiting_user",
    "run.restarted",
    "run.finished",
    "run.failed",
  ].forEach((name) => {
    source.addEventListener(name, (event) => {
      const message = event as MessageEvent<string>;
      onEvent(name, JSON.parse(message.data));
    });
  });
  return source;
}
