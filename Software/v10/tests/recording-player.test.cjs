const { test } = require('node:test')
const assert = require('node:assert/strict')
const { recordingFrames } = require('../frontend/assets/recording-player.js')

function readerFor(bytes, chunkSize = 1) {
  // Simula a divisão dos dados em pacotes de tamanhos arbitrários.
  return new ReadableStream({ start(controller) {
    for (let n = 0; n < bytes.length; n += chunkSize) controller.enqueue(bytes.subarray(n, n + chunkSize))
    controller.close()
  } }).getReader()
}
const part = (position, data) => Buffer.concat([Buffer.from(`--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${data.length}\r\nX-Position: ${position}\r\nX-Duration: 2\r\n\r\n`), data, Buffer.from('\r\n')])

test('reassembles headers and JPEG split across arbitrary network chunks', async () => {
  const bytes = Buffer.concat([part(1, Buffer.from([0, 255, 13, 10])), part(2, Buffer.from([3, 5]))])
  for (const chunkSize of [1, 7, bytes.length]) {
    const frames = []
    for await (const frame of recordingFrames(readerFor(bytes, chunkSize))) frames.push(frame)
    assert.deepEqual(frames.map(f => f.position), [1, 2])
    assert.deepEqual([...frames[0].jpeg], [0, 255, 13, 10])
    assert.equal(frames[1].duration, 2)
  }
})
test('rejects truncated frames instead of silently freezing', async () => {
  // Gravação incompleta precisa produzir erro, não congelar a interface.
  const bytes = part(1, Buffer.from([1, 2, 3])).subarray(0, -3)
  await assert.rejects(async () => { for await (const _ of recordingFrames(readerFor(bytes))) {} }, /interrompida/)
})
test('rejects unbounded frame allocation', async () => {
  const bytes = Buffer.from('--frame\r\nContent-Length: 9000000\r\n\r\n')
  await assert.rejects(async () => { for await (const _ of recordingFrames(readerFor(bytes))) {} }, /inválido/)
})
