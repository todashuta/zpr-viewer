/* =====================================================================
   ヘッドレス検証用の注入スクリプト

   zpr-viewer.html の installUI() の後ろに差し込んで使う（build_test_page.py がやる）。
   実ファイルのビルドには絶対に入れない。

   ?f=xxx.zpr          : 読むファイル
   &mode=0..4          : 表示モード
   &case=uvcorners     : テクスチャ 4 隅の色と UV 値を読み取って貼り向きを検証する
   &case=wire          : 方眼を消してワイヤー線のピクセル数を数える
   &wire=0             : (case=wire) ワイヤー重ねをオフにしてから測る
   &case=buffers       : 頂点バッファ規模と索引の最大値、単独 draw のエラー码を読む
   &case=help          : ? キーでキー一覧が出て閉じられるか
   &case=lightbox      : テクスチャの拡大表示が開くか、閉じられるか
   &case=pan           : pan() の移動方向をカメラ軸で検証する
   &case=reset         : 視点リセット後のカメラ距離を読む
   &wirecolor=255,0,0  : (case=wire) 線色を差し替えて描画の有無を切り分ける
   &nowrite=1          : (case=wire) 面塗りだけを消して線単体で測る
   &lightcol=dir       : (case=wire) 照明色を旧表示（向きベクトルを色に流用）に戻す
   ===================================================================== */
(async () => {
  // headless では requestAnimationFrame が飛んでこないので擬似化する
  window.requestAnimationFrame = cb => setTimeout(() => cb(performance.now()), 0);
  const out = document.createElement('pre');
  out.style.cssText = 'position:fixed;left:0;top:0;z-index:99;color:#0f0;font:12px/1.5 monospace;white-space:pre-wrap';
  document.body.appendChild(out);
  const report = o => { out.textContent = JSON.stringify(o, null, 1); };
  const q = new URLSearchParams(location.search);

  try {
    const target = q.get('f') || 'tests/samples/blender_out.zpr';   // ?f= 無しで開いた時の既定
    const mode = +(q.get('mode') || 0);
    const buf = await (await fetch(target)).arrayBuffer();
    if (q.get('wire') === '0') {
      // openFile は既存の viewer を使い回すので、先に作ってから既定値を落としておく。
      // こうしないと openFile 中の初回描画でワイヤーが構築されてしまう
      viewer = new Viewer(canvas);
      installCamera(viewer);
      startLoop(viewer);
      viewer.wireOverlay = false;
    }
    await openFile(new File([buf], target));
    if (!viewer || !viewer.model) {
      report({ opened: false, toast: document.getElementById('toast').textContent });
      return;
    }
    if (q.get('wire') === '0') viewer.wireOverlay = false;   // 初回描画前に落として、遅延構築されるか確かめる
    if (mode) setMode(mode);
    for (let i = 0; i < 10; i++) { await new Promise(r => setTimeout(r, 40)); viewer.draw(); }

    const gl = viewer.gl, w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    const read = () => { const p = new Uint8Array(w * h * 4); gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, p); return p; };
    let px = read();
    const bg = viewer.bg.map(x => Math.round(x * 255));

    // 背景との差分画素数と平均色。「映っているか」を数値で見るための基本量
    const stats = () => {
      let n = 0; const sum = [0, 0, 0];
      for (let i = 0; i < w * h; i++) {
        if (Math.abs(px[i * 4] - bg[0]) + Math.abs(px[i * 4 + 1] - bg[1]) + Math.abs(px[i * 4 + 2] - bg[2]) > 12) {
          n++; sum[0] += px[i * 4]; sum[1] += px[i * 4 + 1]; sum[2] += px[i * 4 + 2];
        }
      }
      return {
        coverage: +(n / (w * h) * 100).toFixed(2) + '%',
        avg: sum.map(x => Math.round(x / Math.max(1, n))),
      };
    };

    const res = {
      file: target, mode,
      verts: viewer.model.vertexCount, faces: viewer.model.triangleCount,
      texGroups: viewer.texGroups.length, decodedTex: [...viewer.texCache.keys()],
      texNames: viewer.model.textures.map(t => t.name),
      grid: !!viewer.gridBuf, wireBuf: !!viewer.gpu.wire,
      plainFaces: viewer.model.idxPlain.length / 3,
      glError: gl.getError(), ...stats(),
    };

    // --- UV の向き検証：既知の 4 隅カラーが対応する UV 位置に映っているか ---
    if (q.get('case') === 'uvcorners') {
      viewer.wireOverlay = false;    // ワイヤーは色サンプルのノイズになるので引かない
      // Blender の plane の UV：左下=(0,0) … 右上=(1,1)。
      // モデルのスケールは mm（Blender の 1 = 1000）なので bound から割合で位置を決める
      const b = viewer.model.bound;
      const pt = (fx, fy) => [b.min[0] + (b.max[0] - b.min[0]) * fx,
                              b.min[1] + (b.max[1] - b.min[1]) * fy,
                              b.min[2] + (b.max[2] - b.min[2]) * 0.5];
      const PROBE = [
        { uv: '(0,0)', u: 0.15, v: 0.15, expect: '青' },
        { uv: '(1,0)', u: 0.85, v: 0.15, expect: 'マゼンタ' },
        { uv: '(1,1)', u: 0.85, v: 0.85, expect: '緑' },
        { uv: '(0,1)', u: 0.15, v: 0.85, expect: '赤' },
      ];
      // 画像の 4 隅に別々の色を塗ってあるので、そこに映る色でテクスチャの向きが分かる。
      // 黒（＝何も映っていない）も別枠にして、画面外と混同しないようにする
      const PAL = { 赤: [1, 0, 0], 緑: [0, 1, 0], 青: [0, 0, 1], マゼンタ: [1, 0, 1], グレー: [1, 1, 1], 黒: [0, 0, 0] };
      const nearest = v => {
        const m = Math.max(...v) || 1;
        const a = v.map(x => x / m);
        let best = '?', bd = 1e9;
        for (const k in PAL) {
          const d = Math.hypot(a[0] - PAL[k][0], a[1] - PAL[k][1], a[2] - PAL[k][2]);
          if (d < bd) { bd = d; best = k; }
        }
        return best;
      };

      const c = viewer.cam;
      c.yaw = Math.PI / 2; c.pitch = 1.35;
      c.target = [(b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2];

      // 投影は Viewer 内部の行列を再現する（proj は draw() が更新するので draw 直後に読む）
      const project = p => {
        const cp = Math.cos(c.pitch), sp = Math.sin(c.pitch);
        const eye = [c.target[0] + c.dist * cp * Math.cos(c.yaw),
                     c.target[1] + c.dist * cp * Math.sin(c.yaw),
                     c.target[2] + c.dist * sp];
        const view = mat4LookAt(eye, c.target, [0, 0, 1]);
        const P = viewer.proj;
        const vx = view[0] * p[0] + view[4] * p[1] + view[8] * p[2] + view[12];
        const vy = view[1] * p[0] + view[5] * p[1] + view[9] * p[2] + view[13];
        const vz = view[2] * p[0] + view[6] * p[1] + view[10] * p[2] + view[14];
        const vw = view[3] * p[0] + view[7] * p[1] + view[11] * p[2] + view[15];
        const ox = P[0] * vx + P[4] * vy + P[8] * vz + P[12] * vw;
        const oy = P[1] * vx + P[5] * vy + P[9] * vz + P[13] * vw;
        const ow = P[3] * vx + P[7] * vy + P[11] * vz + P[15] * vw;
        return [(ox / ow * 0.5 + 0.5) * w, (oy / ow * 0.5 + 0.5) * h];   // readPixels と同じ下原点
      };

      // サンプル点が画面に収まるまでカメラを引き伸ばす
      const far = () => PROBE.every(pn => {
        const [x, y] = project(pt(pn.u, pn.v));
        return x > 12 && y > 12 && x < w - 12 && y < h - 12;
      });
      let tries = 0;
      c.dist = Math.max(1e-6, b.radius * 2.2);
      for (; tries < 8; tries++) {
        for (let i = 0; i < 2; i++) viewer.draw();   // proj を現在の dist で更新してから判定する
        if (far()) break;
        c.dist *= 1.7;
      }
      for (let i = 0; i < 4; i++) viewer.draw();
      px = read();

      const sample = (p, r = 3) => {
        const [cx, cy] = project([p[0], p[1], p[2], 1]);
        const acc = [0, 0, 0]; let n = 0;
        for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
          const x = Math.round(cx) + dx, y = Math.round(cy) + dy;
          if (x < 0 || y < 0 || x >= w || y >= h) continue;
          const i = (y * w + x) * 4;
          acc[0] += px[i]; acc[1] += px[i + 1]; acc[2] += px[i + 2]; n++;
        }
        return { at: [Math.round(cx), Math.round(cy)], rgb: acc.map(v => Math.round(v / Math.max(1, n))) };
      };

      res.camDist = Math.round(c.dist);   // 失敗時に「カメラ引きが足りなかったか」を見る用
      res.tried = tries;
      res.inView = far();
      // UV 表示モード（uMode=4）では gl_FragColor = vec4(u, v, 0.5, 1)。照明も sRGB 変換も通らない
      res.corners = PROBE.map(pn => {
        const s = sample(pt(pn.u, pn.v), 2);
        const got = s.rgb.map(v => +(v / 255).toFixed(3));
        const color = nearest(s.rgb);
        return {
          uv: pn.uv, at: s.at,
          expect: [pn.u, pn.v], got: got.slice(0, 2),
          ok: Math.abs(got[0] - pn.u) < 0.12 && Math.abs(got[1] - pn.v) < 0.12,
          expectColor: pn.expect, color,
          colorOk: color === pn.expect,
        };
      });
      res.uvPass = res.inView && res.corners.every(cn => cn.ok);
      res.texPass = res.inView && res.corners.every(cn => cn.colorOk);
    }

    // --- バッファ規模とインデックス範囲 ---
    if (q.get('case') === 'buffers') {
      const gp = viewer.gpu, gl = viewer.gl;
      const size = (buf, target) => { gl.bindBuffer(target, buf); return gl.getBufferParameter(target, gl.BUFFER_SIZE); };
      const maxOf = a => { let x = 0; for (let i = 0; i < a.length; i++) if (a[i] > x) x = a[i]; return x; };
      res.buffers = {
        posBytes: size(gp.pos, gl.ARRAY_BUFFER),
        posVerts: size(gp.pos, gl.ARRAY_BUFFER) / 12,
        idxAllBytes: gp.idx ? size(gp.idx, gl.ELEMENT_ARRAY_BUFFER) : null,
        idxAllMax: maxOf(viewer.model.idxAll),
        wireMax: maxOf(viewer.model.wire),
        nv: viewer.model.vertexCount, nt: viewer.model.triangleCount,
      };
      // 個別の draw でエラーが出るか確認する
      const gl2 = viewer.gl;
      gl2.getError();
      gl2.useProgram(viewer.progs.line.p);
      gl2.bindBuffer(gl2.ARRAY_BUFFER, gp.pos);
      gl2.enableVertexAttribArray(viewer.progs.line.a.aPos);
      gl2.vertexAttribPointer(viewer.progs.line.a.aPos, 3, gl2.FLOAT, false, 0, 0);
      gl2.bindBuffer(gl2.ELEMENT_ARRAY_BUFFER, gp.wire);
      gl2.drawElements(gl2.LINES, viewer.model.wire.length, gl2.UNSIGNED_INT, 0);
      res.buffers.errAfterWire = gl2.getError();
    }

    // --- ワイヤーが実際に引かれているか ---
    // 方眼もワイヤーと同じインク色なので、方眼を消してからその色を読み取る
    if (q.get('case') === 'wire') {
      viewer.showGrid = false;
      if (q.get('wire') === '0') viewer.wireOverlay = false;   // 重ねていない状態も測れるようにする
      if (q.get('lightcol') === 'dir') {   // 旧表示（光源の向きを色に流用したもの）との比較用
        viewer.draw();
        viewer.keyCol = viewer.keyDir; viewer.fillCol = viewer.fillDir;
      }
      if (q.get('nowrite')) {     // 塗りだけ消して線単体で測る
        if (viewer.gpu.idx) viewer.gpu.idx.count = 0;
        (viewer.texGroups || []).forEach(g => { g.count = 0; });
      }
      if (q.get('wirecolor')) {   // 線色を差し替えて描画自体の有無を切り分ける
        const wc = q.get('wirecolor').split(',').map(x => +x / 255);
        viewer.ink = a => [wc[0], wc[1], wc[2], a];
      }
      for (let i = 0; i < 4; i++) viewer.draw();
      px = read();
      const ink = viewer.ink(1.0).map(x => Math.round(x * 255));
      let n = 0;
      for (let i = 0; i < w * h; i++) {
        if (Math.abs(px[i * 4] - ink[0]) + Math.abs(px[i * 4 + 1] - ink[1]) + Math.abs(px[i * 4 + 2] - ink[2]) < 60) n++;
      }
      res.ink = ink;
      res.wirePx = n;
      res.grid = false;
      // stats() は先に取ったままだから、方眼・ワイヤーを消した後で読み直す
      const after = stats();
      res.wireBuf = !!viewer.gpu.wire;
      res.coverageNoGrid = after.coverage;   // 方眼を消したので、これはメッシュ自体の被面積
      res.avgNoGrid = after.avg;             // 方眼・ワイヤー抜きの平均色（照明の色を見るのに使う）
    }

    // --- 視点リセットの距離 ---
    if (q.get('case') === 'reset') {
      const c = viewer.cam;
      viewer.fitCamera();
      const fit = c.dist;
      c.dist = 1;
      resetView();
      res.fitDist = Math.round(fit);
      res.resetDist = Math.round(c.dist);
      res.resetYaw = +c.yaw.toFixed(3);
    }

    // --- パンがドラッグした方向にシーンを追従させるか ---
    // 期待する軸は draw が使うビュー行列から拾う（pan の数式を写すと自己証明になる）
    if (q.get('case') === 'pan') {
      const c = viewer.cam;
      c.yaw = Math.PI * 0.5; c.pitch = 0.4; c.dist = viewer.model.bound.radius * 3;
      const cp = Math.cos(c.pitch), sp = Math.sin(c.pitch);
      const eye = [c.target[0] + c.dist * cp * Math.cos(c.yaw),
                   c.target[1] + c.dist * cp * Math.sin(c.yaw),
                   c.target[2] + c.dist * sp];
      const view = mat4LookAt(eye, c.target, [0, 0, 1]);
      const right = [view[0], view[4], view[8]];   // カメラの X 軸 = 画面右
      const up = [view[1], view[5], view[9]];      // カメラの Y 軸 = 画面Up
      const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
      const move = (dx, dy) => {
        const t0 = c.target.slice();
        pan(viewer, dx, dy);
        return [0, 1, 2].map(i => c.target[i] - t0[i]);
      };
      const toRight = move(100, 0);    // マウスを右に 100px
      const toDown = move(0, 100);     // マウス下に 100px（画面座標なので dy は正）
      c.target = [0, 1, 2].map(i => c.target[i] - toRight[i] - toDown[i]);
      res.pan = {
        rightDotX: +dot(toRight, right).toFixed(5),   // 視点は画面左へ滑る＝負
        rightDotY: +dot(toRight, up).toFixed(5),      // 縦方向に漏れない＝0
        downDotY: +dot(toDown, up).toFixed(5),        // 視点は画面Upへ滑る＝正
        downDotX: +dot(toDown, right).toFixed(5),     // 横方向に漏れない＝0
      };
    }

    // --- テクスチャの拡大表示（ライトボックス） ---
    if (q.get('case') === 'lightbox') {
      const ths = document.querySelectorAll('#thumbs .th');
      if (ths.length) ths[0].click();
      res.lightbox = {
        thumbs: ths.length,
        shown: document.getElementById('lightbox').classList.contains('show'),
        hasImage: !!document.getElementById('lbimg').getAttribute('src'),
        hasDownload: !!document.getElementById('lbdl'),
        caption: document.getElementById('lbname').textContent,
      };
      // 縁のピクセルを読む用途なので、枠や角丸で欠けないこと
      const cs = getComputedStyle(document.getElementById('lbimg'));
      res.lightbox.imgRadius = cs.borderTopLeftRadius;
      res.lightbox.imgBorder = cs.borderTopWidth;
      if (ths.length > 1) { stepLightbox(1); res.lightbox.steps = lbIndex; }
      closeLightbox();
      res.lightbox.closed = !document.getElementById('lightbox').classList.contains('show');
    }

    // --- ? キーのショートカット一覧 ---
    if (q.get('case') === 'help') {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));
      res.help = {
        shown: document.getElementById('shorthelp').classList.contains('show'),
        rows: document.querySelectorAll('#helpkeys tr').length,
        dropTable: document.querySelectorAll('#drop table').length,
        dropHint: document.querySelector('#drop .hint').textContent.trim(),
        tipsText: document.getElementById('tips').textContent.replace(/\s+/g, ' ').trim(),
      };
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      res.help.closedByEsc = !document.getElementById('shorthelp').classList.contains('show');
      window.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));
      res.help.openAgain = document.getElementById('shorthelp').classList.contains('show');
      window.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));
      res.help.closedByQuestion = !document.getElementById('shorthelp').classList.contains('show');
    }

    report(res);
  } catch (e) {
    report({ ERROR: e.message, stack: String(e.stack).split('\n').slice(0, 5) });
  }
})();
