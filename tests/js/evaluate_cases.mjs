/** JSON-in/JSON-out adapter used only by the Python--JavaScript differential. */

import {
  BROWSER_API_VERSION,
  IMPLEMENTATION_VERSION,
  INTERPRETATION_LIMIT,
  OPPONENT_NOISE_RATIO,
  SURROUNDS,
  compareModelsWithDiagnostics,
} from "../../cam16_compare.mjs";

let input = "";
for await (const chunk of process.stdin) {
  input += chunk;
}

const request = JSON.parse(input);
if (request.action === "metadata") {
  process.stdout.write(
    JSON.stringify({
      BROWSER_API_VERSION,
      IMPLEMENTATION_VERSION,
      INTERPRETATION_LIMIT,
      OPPONENT_NOISE_RATIO,
      surrounds: SURROUNDS,
    }),
  );
} else if (request.action === "evaluate") {
  const results = request.cases.map((item) => {
    try {
      return { ok: true, value: compareModelsWithDiagnostics(item) };
    } catch (error) {
      return {
        ok: false,
        error: {
          name: error?.name ?? "Error",
          message: error?.message ?? String(error),
        },
      };
    }
  });
  process.stdout.write(JSON.stringify(results));
} else {
  throw new Error(`unknown action: ${request.action}`);
}
