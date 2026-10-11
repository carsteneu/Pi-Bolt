// Monomorphic property read: one object shape, a read site that sees only it.
// Exercises the GetById path (on x86-64: the front end placeholder -> RawGetById in C++).
const N = 20000;
const R = 4000;
class P { constructor(a, b) { this.a = a; this.b = b; } }
const xs = new Array(N);
for (let i = 0; i < N; i++) xs[i] = new P(i, (i * 7) & 1023);
let s = 0;
for (let r = 0; r < R; r++) {
  for (let i = 0; i < N; i++) {
    const o = xs[i];
    s = (s + o.a + o.b) % 1000003;
  }
}
console.log("prop-mono", s);
