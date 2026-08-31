/**
 * Fires the `Sample commute times` workflow on a precise schedule.
 *
 * GitHub's own cron is best-effort and quietly skips slots under load, which
 * puts holes in a time-of-day curve exactly where the load is — peak hours.
 * Cloudflare's Cron Triggers fire on time, so this Worker owns the clock and
 * GitHub owns the work.
 *
 * `force: false` matters: it leaves the window check to sample_commute.py, so
 * a trigger outside a sampling window exits without writing a row.
 */

const OWNER = "sesenht";
const REPO = "commute-tracker";
const WORKFLOW = "sample.yml";
const REF = "main";

async function dispatch(env) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      // GitHub rejects API requests that do not identify themselves.
      "User-Agent": `${OWNER}-commute-tracker-worker`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ref: REF,
      inputs: { force: false, mock: false },
    }),
  });

  // A successful dispatch is 204 with an empty body.
  if (response.status !== 204) {
    const detail = await response.text();
    throw new Error(`dispatch failed: ${response.status} ${detail.slice(0, 300)}`);
  }
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },

  // GET the Worker's URL to test the token and the dispatch path by hand.
  async fetch(request, env) {
    try {
      await dispatch(env);
      return new Response("dispatched\n", { status: 200 });
    } catch (err) {
      return new Response(`${err.message}\n`, { status: 500 });
    }
  },
};
