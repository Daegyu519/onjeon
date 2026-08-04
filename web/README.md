# React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

## `tslib`를 지우지 말 것

우리 코드는 `tslib`를 import하지 않는다. 그런데 `echarts-for-react@3.0.6`의
`esm/index.js`가 `tslib`를 import하면서 자기 `dependencies`에 적어두지 않았다(상판 버그).
`echarts`·`zrender`가 각자 `node_modules/` 안에 tslib를 갖고 있지만 node 해석 규칙상
`echarts-for-react`에서는 그게 안 보인다. 그래서 `web/node_modules`에 tslib가 없으면
`npm run build`가 "Rolldown failed to resolve import tslib"로 **실패**한다 → `serve.sh`가
`set -e`로 멈추고 서버가 아예 안 뜬다.

개발 기기에서 이게 드러나지 않았던 이유: `~/node_modules/tslib`가 있으면 node가 상위
디렉터리로 올라가며 그걸 주워온다. 그 기기 밖(=심사위원 환경)에서만 깨진다.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and Oxlint's TypeScript related rules in your project.
