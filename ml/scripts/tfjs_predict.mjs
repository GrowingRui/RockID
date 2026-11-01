// Runs a TF.js graph model from disk on a float32 input and writes the output (Phase 2 smoke test).
// Pure @tensorflow/tfjs on the CPU backend, so no native build is needed.
// Usage: node tfjs_predict.mjs <model_dir> <input.bin> <input.json (shape)> <output.bin>
import * as tf from '@tensorflow/tfjs';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [modelDir, inputBin, shapeJson, outBin] = process.argv.slice(2);
await tf.setBackend('cpu');

const mj = JSON.parse(readFileSync(join(modelDir, 'model.json'), 'utf8'));
const weightSpecs = [];
const shards = [];
for (const group of mj.weightsManifest) {
  weightSpecs.push(...group.weights);
  for (const p of group.paths) shards.push(readFileSync(join(modelDir, p)));
}
const all = Buffer.concat(shards);
const weightData = all.buffer.slice(all.byteOffset, all.byteOffset + all.byteLength);

const model = await tf.loadGraphModel(
  tf.io.fromMemory({ ...mj, weightSpecs, weightData }),
);

const shape = JSON.parse(readFileSync(shapeJson, 'utf8'));
const raw = readFileSync(inputBin);
const x = tf.tensor(new Float32Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength)), shape, 'float32');
let y = model.predict(x);
if (Array.isArray(y)) y = y[0];
else if (!(y instanceof tf.Tensor)) y = Object.values(y)[0];

const data = await y.data();
writeFileSync(outBin, Buffer.from(data.buffer, data.byteOffset, data.byteLength));
console.log(JSON.stringify({
  backend: tf.getBackend(),
  inputs: model.inputs.map((i) => ({ name: i.name, shape: i.shape, dtype: i.dtype })),
  outputShape: y.shape,
}));
