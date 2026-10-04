// Runs btw on Pyodide off the main thread, so an endless doomscroll can't
// freeze the page: index.html terminates this worker when a run takes too long.
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";

// The page passes its build as ?v=, so this worker fetches files from the same
// build as the page, never stale ones from the browser cache.
const BUILD = new URL(import.meta.url).searchParams.get("v");

async function fetchOk(path) {
  const url = `${path}?v=${BUILD}`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response;
}

const ready = (async () => {
  const pyodide = await loadPyodide();
  const { wheel } = await (await fetchOk("playground.json")).json();
  // Unpacking the wheel directly skips micropip, which would also install
  // pygls: only the language server needs it, and the playground never loads it.
  pyodide.unpackArchive(await (await fetchOk(wheel)).arrayBuffer(), "wheel");
  pyodide.FS.writeFile("play.py", await (await fetchOk("play.py")).text());
  return pyodide.pyimport("play");
})();

ready.then(
  () => postMessage({ type: "ready" }),
  (error) => postMessage({ type: "failed", error: String(error) }),
);

// A message runs one program, or several for the Two Sum tests: one per test,
// all the same code with a different array. Their diagnostics match, so only
// the first program's are shown. With `asm`, its assembly comes next, before
// the run, so a program stopped for running too long still shows it.
// `runtime` names a microservice whose inferred O() comes back with the runs.
onmessage = async ({ data }) => {
  const play = await ready;
  try {
    postMessage({ type: "diagnostics", id: data.id, text: play.check(data.sources[0]) });
    if (data.asm) postMessage({ type: "asm", id: data.id, text: play.asm(data.sources[0]) });
    const runs = data.sources.map((source) => JSON.parse(play.run(source, data.stdin)));
    const runtime = data.runtime ? JSON.parse(play.runtime(data.sources[0], data.runtime)) : null;
    postMessage({ type: "result", id: data.id, runs, runtime });
  } catch (error) {
    postMessage({ type: "result", id: data.id, crash: String(error) });
  }
};
