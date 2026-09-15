import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const submitLatency = new Trend('submit_latency_ms');
const errors = new Rate('submit_errors');

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 5),
      timeUnit: '1s',
      duration: __ENV.DURATION || '60s',
      preAllocatedVUs: 50,
      maxVUs: 500,
    },
  },
  thresholds: {
    'submit_latency_ms': ['p(99)<500'],
    'submit_errors': ['rate<0.001'],
  },
};

const TILES = Number(__ENV.TILES || 200);

export default function () {
  const offset = Math.floor(Math.random() * 6000);
  const res = http.post(
    'http://localhost:8000/jobs',
    JSON.stringify({ n_tiles: TILES, offset: offset }),
    { headers: { 'Content-Type': 'application/json' } }
  );

  submitLatency.add(res.timings.duration);
  errors.add(res.status !== 202);
  check(res, { 'status 202': (r) => r.status === 202 });
}
