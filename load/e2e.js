import http from 'k6/http';
import { sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

const e2eSeconds = new Trend('job_e2e_seconds');
const firstTileSeconds = new Trend('time_to_first_tile_seconds');
const timeouts = new Counter('job_timeouts');
const submitted = new Counter('jobs_submitted');
const completed = new Counter('jobs_completed');
const failures = new Rate('job_failures');

const MAX_WAIT = Number(__ENV.MAX_WAIT || 240);

export const options = {
  scenarios: {
    jobs: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 1),
      timeUnit: __ENV.UNIT || '10s',
      duration: __ENV.DURATION || '3m',
      preAllocatedVUs: 20,
      maxVUs: 200,
      gracefulStop: `${MAX_WAIT + 30}s`,
    },
  },
  thresholds: {
    'job_e2e_seconds': ['p(95)<120'],
    'time_to_first_tile_seconds': ['p(95)<5'],
    'job_failures': ['rate<0.001'],
  },
};

const TILES = Number(__ENV.TILES || 200);

export default function () {
  const t0 = Date.now();
  const offset = Math.floor(Math.random() * 6000);

  submitted.add(1);

  const res = http.post(
    'http://localhost:8000/jobs',
    JSON.stringify({ n_tiles: TILES, offset: offset }),
    { headers: { 'Content-Type': 'application/json' } }
  );

  if (res.status !== 202) {
    failures.add(true);
    e2eSeconds.add(MAX_WAIT);
    firstTileSeconds.add(MAX_WAIT);
    return;
  }

  const jobId = res.json('job_id');
  let sawFirstTile = false;

  while ((Date.now() - t0) / 1000 < MAX_WAIT) {
    sleep(1);
    const p = http.get(`http://localhost:8000/jobs/${jobId}`);
    if (p.status !== 200) continue;

    const done = p.json('completed');
    const elapsed = (Date.now() - t0) / 1000;

    if (!sawFirstTile && done > 0) {
      firstTileSeconds.add(elapsed);
      sawFirstTile = true;
    }

    if (p.json('status') === 'complete') {
      e2eSeconds.add(elapsed);
      completed.add(1);
      failures.add(false);
      return;
    }
  }

  timeouts.add(1);
  failures.add(true);
  e2eSeconds.add(MAX_WAIT);
  if (!sawFirstTile) firstTileSeconds.add(MAX_WAIT);
}
