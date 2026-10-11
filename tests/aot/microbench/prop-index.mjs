// Property read by a computed name: the key is a string that is not a constant, so
// the site is a GetByVal with a property name. On x86-64 the stub has no megamorphic
// cache lookup for that case and every access goes to RawGetByVal in C++.
const N = 20000;
const R = 4000;
const keys = ["a", "b", "c", "d", "e", "f"];
class A { constructor(a, b) { this.a = a; this.b = b; } }
class B { constructor(a, b, c) { this.a = a; this.b = b; this.c = c; } }
class C { constructor(q, a, b) { this.q = q; this.a = a; this.b = b; } }
const makers = [
  (i) => new A(i, i & 1023),
  (i) => new B(i, i & 1023, i & 15),
  (i) => new C(i & 3, i, i & 1023),
];
const xs = new Array(N);
for (let i = 0; i < N; i++) xs[i] = makers[i % makers.length](i);
let s = 0;
for (let r = 0; r < R; r++) {
  for (let i = 0; i < N; i++) {
    const o = xs[i];
    s = (s + o[keys[i % 2]]) % 1000003;
  }
}
console.log("prop-index", s);
