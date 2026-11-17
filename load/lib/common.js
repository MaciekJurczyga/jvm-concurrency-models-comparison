import http from 'k6/http';

export const BASE_URL = __ENV.BASE_URL || 'http://sut:8080';
export const ENDPOINT = required('ENDPOINT');

// A request still pending after this is a client-side timeout and counts as an error (plan section 5).
const REQUEST_TIMEOUT = __ENV.REQUEST_TIMEOUT || '10s';

// Iterations still running when a phase/scenario ends may finish for this long, so slow responses near
// a phase boundary are recorded under their own phase instead of being cut off. Must exceed REQUEST_TIMEOUT.
export const GRACEFUL_STOP = __ENV.GRACEFUL_STOP || '15s';

export function required(name) {
  const v = __ENV[name];
  if (v === undefined || v === '') {
    throw new Error(`missing required env ${name}`);
  }
  return v;
}

export function num(name, fallback) {
  const v = __ENV[name];
  if (v === undefined || v === '') {
    if (fallback === undefined) throw new Error(`missing required env ${name}`);
    return fallback;
  }
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error(`env ${name} is not a number: ${v}`);
  return n;
}

export function hit(tags) {
  return http.get(`${BASE_URL}${ENDPOINT}`, { timeout: REQUEST_TIMEOUT, tags });
}

export const commonOptions = {
  // Bodies are 16-23 B and never inspected; discarding them keeps k6 CPU low (k6 must not be the bottleneck).
  discardResponseBodies: true,
  tags: { endpoint: ENDPOINT },
  summaryTrendStats: ['min', 'med', 'avg', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

// The runner passes SUMMARY_PATH (results/<series>/<run>/...). Without it nothing is printed: an exported
// handleSummary replaces the default end-of-test summary, so manual checks read metrics in Prometheus/Grafana.
export function handleSummary(data) {
  if (!__ENV.SUMMARY_PATH) {
    return {};
  }
  return { [__ENV.SUMMARY_PATH]: JSON.stringify(data, null, 2) };
}
