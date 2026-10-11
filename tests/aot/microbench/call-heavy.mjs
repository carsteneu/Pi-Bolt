// Call-heavy: a monomorphic call site of a small function, plus a call through a
// property read (o.add), which is a GetById followed by a call. Exercises Stub::Call
// and the property read that precedes it.
const N = 20000;
const R = 2000;
class Counter {
  constructor(v) { this.v = v; }
  add(x) { return (this.v + x) & 0x3fffff; }
}
function bump(v, x) { return (v + x + 1) & 0x3fffff; }
const xs = new Array(N);
for (let i = 0; i < N; i++) xs[i] = new Counter(i);
let s = 0;
for (let r = 0; r < R; r++) {
  for (let i = 0; i < N; i++) {
    const o = xs[i];
    s = bump(s, i & 63);
    s = o.add(s) % 1000003;
  }
}
console.log("call-heavy", s);
