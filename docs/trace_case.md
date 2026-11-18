# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `swarm C-002@55`, run ID `R-swarm-C-002-s55` |
| Triệu chứng | Grader fail: status `resolved` != `denied`; ledger ghi hoàn 20.000đ trong khi nhãn là 0đ |
| Bước sai đầu tiên | Bước 3: `model_override {"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Bước 1 `handoff` đúng; bước 2 `investigator` tra DB đúng `delay_days: 2`. Sang bước 3 model tin ticket khách ghi đè 5 ngày |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) |
| Đối chứng | Trên shape `fixed` (`C-002@11`): không có bước `model_override`, quote ra 0đ, status `denied` khớp 100% nhãn |
| Regression test | `lab9.graders.RefundAmountCorrect` và `lab9.graders.DbFactKept`; fail trên `swarm@55` và pass trên `fixed` |
| Chưa chắc chắn | Trace chỉ ghi nhận hành vi override có gắn tag; nếu prompt injection tinh vi không sinh event override thì cần trajectory assertion mức ledger |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
