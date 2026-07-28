# NAVICUS 自治体クローラー再監査結果

2026-07-28 に完了した連続再監査ループの確定結果です。

- 対象発注者: 139
- content ○: 139
- content △: 0
- 実案件: 293行（公式URL 291件）
- route P2: 31
- iteration 02 純増○: 3
- 停止理由: `NET_NEW_CIRCLES_BELOW_4`
- iteration 03: 実施しない

## 公開ファイル

- `index.html`: 地方別レビュー・実案件・経路グラフ
- `route-quality.html`: 経路品質31件の確認画面
- `final-audit.json`: 独立最終監査結果
- `loop-state.json`: ループの最終状態

## 正本チェックサム

- canonical overlay: `c6471e22dc8c12ce38dd477fd5674e413c25bbc09642b56a83436c96a43cd0ee`
- canonical case union: `06b3b86d18b3db1885dce13a7dd432d2a874205ccd9a24d76fc5545aebb43286`

最終判定は `GO_CANONICAL_AND_STOP` です。
