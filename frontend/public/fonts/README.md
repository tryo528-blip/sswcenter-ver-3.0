# Local web fonts

The production frontend serves these files locally and never loads a runtime web font or CDN.

## Pretendard (primary)

The app uses the `Pretendard` family first for the UI. Files were bundled from
the official [orioncactus/pretendard](https://github.com/orioncactus/pretendard)
repository at release `v1.3.9` and are loaded locally for weights 100 through
900. The upstream webfont files are under
`packages/pretendard/dist/web/static/woff2/`.

Pretendard license:

- Copyright Orion Cactus; licensed under the SIL Open Font License, Version 1.1.
- Upstream license text: `https://github.com/orioncactus/pretendard/blob/v1.3.9/LICENSE`.

## MaruBuri (fallback)

Included files:

- `MaruBuri-ExtraLight.woff2`
- `MaruBuri-Light.woff2`
- `MaruBuri-Regular.woff2`
- `MaruBuri-SemiBold.woff2`
- `MaruBuri-Bold.woff2`

Source:

- GitHub source repository: `https://github.com/fonts-archive/MaruBuri`
- Bundled source revision: `977eeff68d1d40bcef341f09c1f56cce1903bb8a`
- NAVER Hangul static font distribution: `https://hangeul.pstatic.net/hangeul_static/webfont/MaruBuri/`
- NAVER font license: `https://help.naver.com/service/30016/contents/18088`

The upstream CSS names the family `Maru Buri`; the app keeps the existing
`MaruBuri` alias so existing styles and tests remain compatible. All five
upstream weights are loaded locally to prevent synthetic-weight fallback.

License and copyright:

- Copyright NAVER Corporation; Reserved Font Name `MaruBuri`.
- Licensed under the SIL Open Font License, Version 1.1.
- NAVER's license page explicitly applies the same open-font terms to MaruBuri.

Bundled-file verification (SHA-256):

- `MaruBuri-ExtraLight.woff2`: `A0A2D0E125C360CE4B9B2CD8A880FA089CFC6AF8E7B9DF27C7E1E8F50A248F88`
- `MaruBuri-Light.woff2`: `D357AE74FE5D5BC2BAA889044DD5031C6D8031B8E35A8D99C851F4677C4DB332`
- `MaruBuri-Regular.woff2`: `4DE2250AAA693265594B92B7DBA7D002B042EC6EE09D56BBB30FDA6D112EF835`
- `MaruBuri-SemiBold.woff2`: `340E4DCBF466028565D194CAB86159DC40CEDAF8E38DB5429472A2468D8036F8`
- `MaruBuri-Bold.woff2`: `11C4641D3FE9B33EFCF7C0687DE91A5B6DB724605AB75323557DA138DA543D12`
