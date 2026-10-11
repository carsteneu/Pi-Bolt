// Polymorphic property read: the same read site sees several object shapes, so the
// inline cache is no use and the megamorphic cache is (on x86-64: neither, the front
// end placeholder sends every access to RawGetById in C++).
const N = 20000;
const R = 4000;
class A { constructor(a, b) { this.a = a; this.b = b; } }
class B { constructor(a, b, c) { this.a = a; this.b = b; this.c = c; } }
class C { constructor(q, a, b) { this.q = q; this.a = a; this.b = b; } }
class D { constructor(a, x, y, b) { this.a = a; this.x = x; this.y = y; this.b = b; } }
class E { constructor(a) { this.a = a; this.b = 0; } }
class F { constructor(z, a, b, w) { this.z = z; this.a = a; this.b = b; this.w = w; } }
const makers = [
  (i) => new A(i, i & 1023),
  (i) => new B(i, i & 1023, i & 15),
  (i) => new C(i & 3, i, i & 1023),
  (i) => new D(i, i & 3, i & 5, i & 1023),
  (i) => new E(i),
  (i) => new F(i & 7, i, i & 1023, i & 31),
];
const xs = new Array(N);
for (let i = 0; i < N; i++) xs[i] = makers[i % makers.length](i);
let s = 0;
for (let r = 0; r < R; r++) {
  for (let i = 0; i < N; i++) {
    const o = xs[i];
    s = (s + o.a + o.b) % 1000003;
  }
}
console.log("prop-poly", s);
