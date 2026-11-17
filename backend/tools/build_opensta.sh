#!/bin/sh
# Builds OpenSTA (github.com/parallaxsw/OpenSTA, GPLv3) and its dependencies into ~/.local/opensta
# without Homebrew. Everything stays under ~/.local/opensta; the only file written elsewhere is the
# `sta` shim in ~/.local/bin. Safe to re-run: finished steps are skipped.
#
#   sh ~/.local/opensta/build_all.sh
#
# Needs: git, make, clang (Xcode command line tools), bison 3.8 in ~/.local/bin, and the venv in
# ~/.local/opensta/venv that provides cmake and swig (already created).
set -e
ROOT="$HOME/.local/opensta"; SRC="$ROOT/src"; DEPS="$ROOT/deps"; J=$(sysctl -n hw.ncpu)
export PATH="$ROOT/venv/bin:$HOME/.local/bin:$PATH"
mkdir -p "$SRC" "$DEPS"

echo "== 1/4 Tcl 8.6.16"
if [ ! -x "$DEPS/tcl/bin/tclsh8.6" ]; then
  mkdir -p "$SRC/tcl" && cd "$SRC/tcl"
  [ -f tcl.tar.gz ] || curl -fsSL -o tcl.tar.gz https://github.com/tcltk/tcl/archive/refs/tags/core-8-6-16.tar.gz
  [ -d tcl-core-8-6-16 ] || tar xzf tcl.tar.gz
  cd tcl-core-8-6-16/unix
  ./configure --prefix="$DEPS/tcl" --disable-framework | tail -1
  make -j"$J" | tail -1
  make install | tail -1
fi
echo 'puts "   tcl [info patchlevel] ready"' | "$DEPS/tcl/bin/tclsh8.6"

echo "== 2/4 CUDD 3.0.0"
if [ ! -f "$DEPS/cudd/lib/libcudd.a" ]; then
  mkdir -p "$SRC/cudd" && cd "$SRC/cudd"
  [ -d cudd ] || git clone -q https://github.com/cuddorg/cudd.git cudd
  cd cudd && git checkout -q 3.0.0
  touch aclocal.m4 configure Makefile.in config.h.in 2>/dev/null || true   # stop automake regenerating
  ./configure --prefix="$DEPS/cudd" | tail -1
  make -j"$J" | tail -1
  make install | tail -1
fi
echo "   cudd ready"

echo "== 3/4 Eigen 3.4.0 (headers only)"
if [ ! -f "$DEPS/eigen/share/eigen3/cmake/Eigen3Config.cmake" ]; then
  mkdir -p "$SRC/eigen" && cd "$SRC/eigen"
  [ -f eigen.tar.gz ] || curl -fsSL -o eigen.tar.gz https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.gz
  [ -d eigen-3.4.0 ] || tar xzf eigen.tar.gz
  cmake -S eigen-3.4.0 -B build -DCMAKE_INSTALL_PREFIX="$DEPS/eigen" -DEIGEN_BUILD_DOC=OFF -DBUILD_TESTING=OFF | tail -1
  cmake --install build | tail -1
fi
echo "   eigen ready"

echo "== 4/4 OpenSTA"
if [ ! -x "$SRC/OpenSTA/build/sta" ]; then
  cd "$SRC"
  [ -d OpenSTA ] || git clone -q --depth 1 https://github.com/parallaxsw/OpenSTA.git OpenSTA
  cd OpenSTA
  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    -DCUDD_DIR="$DEPS/cudd" \
    -DTCL_LIBRARY="$DEPS/tcl/lib/libtcl8.6.dylib" -DTCL_HEADER="$DEPS/tcl/include/tcl.h" \
    -DCMAKE_PREFIX_PATH="$DEPS/eigen;$DEPS/tcl" | tail -3
  cmake --build build -j"$J" | tail -3
fi

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/sta" <<'SHIM'
#!/bin/sh
# Shim for OpenSTA built in ~/.local/opensta (see build_all.sh).
exec "$HOME/.local/opensta/src/OpenSTA/build/sta" "$@"
SHIM
chmod +x "$HOME/.local/bin/sta"
echo "== done:"; "$HOME/.local/bin/sta" -version
