// Typed-field read: a class whose layout the AOT compiler may know statically, so a
// property read becomes a ReadSlot stub (on ARM64) instead of the generic path.
// Only reachable with BUN_JSC_useAOTTypedFields=1 (and a type table); without it this
// bench is a plain monomorphic read and its numbers are the same as prop-mono.
const N = 20000;
const R = 4000;
class Pt {
  constructor(x, y) { this.x = x; this.y = y; }
  sum() { return (this.x + this.y) & 0x3fffff; }
}
const xs = new Array(N);
for (let i = 0; i < N; i++) xs[i] = new Pt(i, (i * 5) & 1023);
let s = 0;
for (let r = 0; r < R; r++) {
  for (let i = 0; i < N; i++) {
    const o = xs[i];
    s = (s + o.x * 3 + o.y) % 1000003;
  }
}
console.log("typed-field", s);
