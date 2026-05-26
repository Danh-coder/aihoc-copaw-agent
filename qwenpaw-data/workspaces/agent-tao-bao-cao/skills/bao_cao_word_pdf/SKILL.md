---
name: bao_cao_word_pdf
description: Tao bao cao tu template Word, lay du lieu Random User API theo tham so do user cung cap, xuat PDF va gui file cho user. Luon hoi du tham so truoc khi chay, khong doan gia tri.
---

# Bao Cao Tu Word Template -> PDF

## Bat buoc truoc khi chay

Ban phai hoi user day du tham so. Khong duoc tu doan:

1. report_title
2. report_period
3. generated_by
4. summary_text
5. results (so user can lay)
6. nat (co the de trong)
7. gender (co the de trong)
8. seed (co the de trong)

Neu thieu tham so bat buoc thi hoi lai cho den khi du.

Sau khi da du tham so, bat buoc validate va confirm voi user truoc khi chay:

1. `results` (so_nguoi) phai la so nguyen > 0.
2. `gender` chi duoc la `male`, `female`, hoac rong.
3. `nat` de rong hoac dung danh sach ma RandomUser ho tro (co the comma-separated):
  `AU,BR,CA,CH,DE,DK,ES,FI,FR,GB,IE,IN,IR,MX,NL,NO,NZ,RS,TR,UA,US`.
4. `ten_file` phai khong rong.
5. Gui lai bang tom tat params va hoi user xac nhan (yes/no). Chi chay khi user dong y.

## Input/Output

- Template mac dinh: `templates/demo_bao_cao_template.docx`
- Script: `scripts/generate_report.py`
- Thu muc output: `reports/`
- Script tao:
  - 1 file Word da dien du lieu
  - 1 file PDF de gui cho user

## Cach chay

Tu workspace `agent-tao-bao-cao`, chay lenh mau:

```bash
python skills/bao_cao_word_pdf/scripts/generate_report.py \
  --template templates/demo_bao_cao_template.docx \
  --output-dir reports \
  --report-title "Bao cao demo" \
  --report-period "Tuan 20/2026" \
  --generated-by "Nguyen Van A" \
  --summary-text "Tom tat theo yeu cau user" \
  --results 5 \
  --nat us,gb \
  --gender female \
  --seed qwenpaw-demo
```

## Sau khi script thanh cong

1. Doc JSON output cua script, lay `pdf_path`.
2. Goi tool `send_file_to_user` voi `file_path = pdf_path`.
3. Tra loi user ngan gon: da tao xong va da gui file.

## Loi thuong gap

- Neu khong convert duoc PDF, bao user cai LibreOffice (`soffice`) hoac cai `docx2pdf` + Microsoft Word.
- Neu API loi, bao user va cho phep chay lai voi tham so khac.
- Neu `nat` khong hop le (vi du `VN`), bao ro ma khong duoc RandomUser ho tro va de nghi user chon ma hop le.

## Contract khi loi

Neu script fail, phan hoi user theo format ngan gon:

1. `status=failed`
2. `error=<root-cause>`
3. `next_step=<mot hanh dong cu the de sua>`
