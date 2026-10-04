// Runs btw on Pyodide off the main thread, so an endless doomscroll can't
// freeze the page: index.html terminates this worker when a run takes too long.
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";

async function fetchOk(url) {
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

onmessage = async ({ data }) => {
  const play = await ready;
  try {
    postMessage({ type: "diagnostics", id: data.id, text: play.check(data.source) });
    postMessage({ type: "result", id: data.id, ...JSON.parse(play.run(data.source, data.stdin)) });
  } catch (error) {
    postMessage({ type: "result", id: data.id, crash: String(error) });
  }
};
