# 성장 기록 · Growth log (자동 생성 · generated)

> 어떤 일을 하시든, 당신의 현장이 손자리의 선생입니다.
> 당신이 알려 준 실패는 손자리가 앞으로 영원히 통과해야 할 시험이 됩니다.

> *Whatever your work is, your field experience is Sonjari's teacher.*
> *Every failure you report becomes a test Sonjari must pass, forever.*

날짜를 이름에 단 시험 194개. 손으로 쓰지 않았다 — `scripts/growth_ledger.py` 가 시험 파일의 이름 · 첫 줄 설명 · git 이 그 파일을 처음 들인 날에서 뽑았다. 시험은 지금도 매번 돈다.

*194 tests carry the date of the day something went wrong in their file name. Generated from each test's name, the first line of its description (in Korean — that is the source) and the day git first saw it. Every one of them still runs on every change.*

**이 표가 맞는 정도 · How far to trust this list** (사람이 표본을 읽고 가름 · 2026-10-16)
- 날짜 단 시험 30개 표본 중 **27개가 실제 실패에서 왔다.** 나머지는 새 기능 · 밖에서 받은 가설 · 속도를 견준 뒤 군살 빼기였다.
- 날짜 없는 시험(9월 이후 368개) 표본 30개 중 **17개도 실패에서 왔다** — 그래서 이 표는 실패에서 온 시험의 **절반쯤만** 담는다. 낱말로 짐작해 채우지 않았다.
- *Sampled by reading the tests: 27 of 30 dated tests came from a real failure (the rest: a new feature, an outside hypothesis, a speed clean-up). But 17 of 30 undated tests also came from failures — so this list holds only about half of them. We did not guess the rest from keywords.*

| 날짜 | 무엇을 지키나 | 시험 | git 에 들어온 날 |
|---|---|---|---|
| 2026-10-16 | 모델이 **답을 탭 닫기와 같이 써 버린** 판에서 그 답을 잃지 않는다 (2026-10-16). | [`test_answer_written_with_the_tab_close_1016.py`](tests/test_answer_written_with_the_tab_close_1016.py) | 2026-10-16 |
| 2026-10-15 | 그림을 켠 채로는 빠듯한 카드에서 설정 화면이 「가능」이라 해 놓고 못 올리던 것 (2026-10-15). | [`test_tight_pictures_fall_back_to_text_only_1015.py`](tests/test_tight_pictures_fall_back_to_text_only_1015.py) | 2026-10-15 |
| 2026-10-15 | 문서를 쓴 직후 「다시 읽어 견주기」를 **그림자로** 남긴다 (2026-10-15). | [`test_readback_shadow_record_1015.py`](tests/test_readback_shadow_record_1015.py) | 2026-10-15 |
| 2026-10-15 | 저장한 문서에서 글을 다시 꺼내, 쓰려던 내용이 빠지거나 바뀐 곳을 찾는다 (2026-10-15). | [`test_readback_finds_what_did_not_land_1015.py`](tests/test_readback_finds_what_did_not_land_1015.py) | 2026-10-15 |
| 2026-10-15 | 「돌려받을 항목(needs)」 검사가 **제목 아래 목록**과 **첫 칸이 이름인 표**도 본다 (2026-10-15). | [`test_needs_under_headings_and_row_names_1015.py`](tests/test_needs_under_headings_and_row_names_1015.py) | 2026-10-15 |
| 2026-10-15 | 맡긴 쪽이 밝힌 「돌려받아야 할 것」 · 나가기 전 정제 · 한 줄 영수증 (2026-10-15 · 전략안 §55-32). | [`test_needs_refine_receipt_1015.py`](tests/test_needs_refine_receipt_1015.py) | 2026-10-15 |
| 2026-10-15 | 재는 꾸러미가 **창이 꽉 차 말이 잘린 호출**을 세어 결과 파일에 싣는다 (2026-10-15). | [`test_measure_kit_counts_length_cuts_1015.py`](tests/test_measure_kit_counts_length_cuts_1015.py) | 2026-10-15 |
| 2026-10-15 | 달라는 칸이 **전부 목록에 보이는 칸**이면 「직접 열어 읽기」가 아니라 「목록으로 담기」다 (2026-10-15). | [`test_listing_fields_need_no_opening_1015.py`](tests/test_listing_fields_need_no_opening_1015.py) | 2026-10-15 |
| 2026-10-15 | 일 조회 문(`/v1/jobs/{id}`)이 바깥 AI 가 맡긴 일의 답을 **토큰 없이 읽으면 정제해서** 준다 (2026-10-15). | [`test_job_door_hands_out_the_refined_answer_1015.py`](tests/test_job_door_hands_out_the_refined_answer_1015.py) | 2026-10-15 |
| 2026-10-15 | 모델 실행기가 **잠깐 응답하지 않을 때**도 한 번 다시 묻는다 (2026-10-15). | [`test_an_unresponsive_runner_is_asked_once_more_1015.py`](tests/test_an_unresponsive_runner_is_asked_once_more_1015.py) | 2026-10-15 |
| 2026-10-15 | 한 가게에서 막혀 「진전 없음」이 되어도, **아직 안 간 가게가 남았으면** 한 번은 거기로 보낸다 (2026-10-15). | [`test_a_stuck_shop_does_not_end_the_other_shops_1015.py`](tests/test_a_stuck_shop_does_not_end_the_other_shops_1015.py) | 2026-10-15 |
| 2026-10-15 | 가게 하나가 **점검 중**이면 사람에게 넘기지 않고 남은 가게로 잇는다 (2026-10-15). | [`test_a_site_under_maintenance_is_not_handed_to_a_person_1015.py`](tests/test_a_site_under_maintenance_is_not_handed_to_a_person_1015.py) | 2026-10-15 |
| 2026-10-15 | 결과를 **제목으로** 지목하면 순위를 잘못 세도 그 글이 열린다 (2026-10-15). | [`test_a_result_can_be_named_by_its_title_1015.py`](tests/test_a_result_can_be_named_by_its_title_1015.py) | 2026-10-15 |
| 2026-10-15 | 가게 이름이 첫 칸이 아닌 표도 그 가게의 줄로 센다 (2026-10-15 · 눈금 거짓말). | [`test_a_price_row_is_found_by_any_shop_cell_1015.py`](tests/test_a_price_row_is_found_by_any_shop_cell_1015.py) | 2026-10-15 |
| 2026-10-15 | 옛 Playwright 가 깨끗이 안 닫힌 일꾼 스레드에서는 브라우저가 **영원히** 다시 안 켜진다 — 스레드를 바꿔 한 번 다시 켠다 (2026-10-15). | [`test_a_poisoned_browser_thread_is_replaced_1015.py`](tests/test_a_poisoned_browser_thread_is_replaced_1015.py) | 2026-10-15 |
| 2026-10-15 | 검색 주소를 `browser_open` 으로 직접 연 **목록 화면**은 「직접 열어 읽은 글」이 아니다 (2026-10-15). | [`test_a_listing_opened_by_address_is_not_a_read_1015.py`](tests/test_a_listing_opened_by_address_is_not_a_read_1015.py) | 2026-10-15 |
| 2026-10-15 | 페이지 하나가 응답을 안 해 브라우저가 물리면, 사람에게 넘기지 않고 브라우저를 되살려 남은 가게로 잇는다 (2026-10-15). | [`test_a_hung_page_is_skipped_not_handed_over_1015.py`](tests/test_a_hung_page_is_skipped_not_handed_over_1015.py) | 2026-10-15 |
| 2026-10-15 | 「A **말고** 다른 파일은 고치지 마」에서 A 는 지킬 파일이 아니라 **고칠 파일**이다 (2026-10-15). | [`test_a_file_named_as_the_exception_is_not_protected_1015.py`](tests/test_a_file_named_as_the_exception_is_not_protected_1015.py) | 2026-10-15 |
| 2026-10-15 | 「주제 다섯 · **주제마다** 글 2개」는 2개가 아니라 10개다 (2026-10-15). | [`test_a_count_per_group_is_multiplied_1015.py`](tests/test_a_count_per_group_is_multiplied_1015.py) | 2026-10-15 |
| 2026-10-14 | 표의 두 칸이 모든 줄에서 똑같으면, 쓴 직후에 알린다 (2026-10-14). | [`test_twin_columns_are_pointed_out_1014.py`](tests/test_twin_columns_are_pointed_out_1014.py) | 2026-10-14 |
| 2026-10-14 | 브라우저 연결은 「쌓인 것」을 보고 갈아 끼운다 — 우리가 띄운 크롬에서도 (2026-10-14). | [`test_the_connection_is_swapped_by_what_piled_up_1014.py`](tests/test_the_connection_is_swapped_by_what_piled_up_1014.py) | 2026-10-14 |
| 2026-10-14 | 파일을 쓴 뒤에 새로 읽은 페이지가 있으면, 끝내기 전에 한 번만 다시 쓰게 돌려보낸다 (2026-10-14). | [`test_rewrite_after_reading_1014.py`](tests/test_rewrite_after_reading_1014.py) | 2026-10-14 |
| 2026-10-14 | 파일을 쓴 **뒤에** 새로 읽은 페이지가 있으면 골라낸다 (2026-10-14). | [`test_reads_after_last_write_1014.py`](tests/test_reads_after_last_write_1014.py) | 2026-10-14 |
| 2026-10-14 | 답 끝에 우리가 붙인 「시킨 것 대조」의 숫자는 「도구가 준 적 없는 숫자」로 세지 않는다 (2026-10-14). | [`test_our_checklist_numbers_are_not_claims_1014.py`](tests/test_our_checklist_numbers_are_not_claims_1014.py) | 2026-10-14 |
| 2026-10-14 | 화면 자동화 부품의 COM 정의는 이 PC 용 캐시를 먼저 찾고, 실패한 불러오기는 되풀이하지 않는다 (2026-10-14). | [`test_com_cache_comes_first_1014.py`](tests/test_com_cache_comes_first_1014.py) | 2026-10-14 |
| 2026-10-14 | 머리줄이 값의 **꼴**을 정하는 칸에서 값이 그 꼴과 안 맞으면 **알린다** (2026-10-14). | [`test_column_shape_notes_1014.py`](tests/test_column_shape_notes_1014.py) | 2026-10-14 |
| 2026-10-14 | 모델 실행기가 꺼지면 한 번 다시 묻고, 또 꺼지면 「꺼졌다」고 적는다 (2026-10-14). | [`test_a_stopped_model_runner_is_asked_once_more_1014.py`](tests/test_a_stopped_model_runner_is_asked_once_more_1014.py) | 2026-10-14 |
| 2026-10-14 | 답을 대신 파일로 옮길 때, 사람이 댄 파일 이름 · 자리를 쓴다 (2026-10-14 레딧 홍보 규칙 조사). | [`test_a_saved_answer_keeps_the_asked_name_1014.py`](tests/test_a_saved_answer_keeps_the_asked_name_1014.py) | 2026-10-14 |
| 2026-10-13 | 사이트 검색 결과는 **그려진 뒤에** 센다 (2026-10-13 가격 조사 판의 틀린 칸을 까닭별로 가르다 찾음). | [`test_site_results_are_counted_once_drawn_1013.py`](tests/test_site_results_are_counted_once_drawn_1013.py) | 2026-10-13 |
| 2026-10-13 | 줄은 **파일이 지금 서 있는 대로** 본다 — 쓴 뒤에 고친 칸은 고친 값으로 (2026-10-13 영상 촬영 판). | [`test_rows_are_judged_as_the_file_stands_1013.py`](tests/test_rows_are_judged_as_the_file_stands_1013.py) | 2026-10-13 |
| 2026-10-13 | 「그 ○○」의 ○○ 가 바로 앞 판에 있으면 오랜 기억을 싣지 않는다 (2026-10-13). | [`test_pointing_at_the_previous_turn_keeps_old_memory_out_1013.py`](tests/test_pointing_at_the_previous_turn_keeps_old_memory_out_1013.py) | 2026-10-13 |
| 2026-10-13 | 「글만 읽기」를 목록 밖 모델과, 받아 보니 그림 부속이 따로 붙어 온 모델로 넓힌다 (2026-10-13). | [`test_pictures_come_off_any_model_that_carries_them_apart_1013.py`](tests/test_pictures_come_off_any_model_that_carries_them_apart_1013.py) | 2026-10-14 |
| 2026-10-13 | 재는 꾸러미가 **왜 틀렸는지 · 얼마나 빨랐는지**를 적고, 과제가 끝나면 **자기가 연 탭을 닫는다** (2026-10-13). | [`test_measure_kit_says_why_and_how_fast_1013.py`](tests/test_measure_kit_says_why_and_how_fast_1013.py) | 2026-10-13 |
| 2026-10-13 | 재는 꾸러미가 **판 사이의 흔들림**과 「이 차이를 가려내려면 몇 판」을 같이 적는다 (2026-10-13). | [`test_measure_kit_says_how_shaky_1013.py`](tests/test_measure_kit_says_how_shaky_1013.py) | 2026-10-13 |
| 2026-10-13 | 이 PC 에서 재 보기(`measure_kit`) — 채점은 쓰던 자와 같고, 결과 파일에는 숫자와 예 · 아니오만 실린다 (2026-10-13). | [`test_measure_kit_1013.py`](tests/test_measure_kit_1013.py) | 2026-10-13 |
| 2026-10-13 | 지어낸 검색 주소는 **인자 이름이 달라도 · 검색어가 경로에 실려 있어도** 알아보고 검색칸에 대신 친다 (2026-10-13). | [`test_made_up_search_addresses_are_typed_1013.py`](tests/test_made_up_search_addresses_are_typed_1013.py) | 2026-10-13 |
| 2026-10-13 | 「○○ 파일로 줘」는 파일 요청이다 · 도구 없이 쓴 답이 「저장했습니다」라고 하면 답이 아니다 (2026-10-13). | [`test_file_asks_and_file_claims_1013.py`](tests/test_file_asks_and_file_claims_1013.py) | 2026-10-13 |
| 2026-10-13 | 워드 표의 칸 너비 — 긴 주소 한 칸이 폭을 다 차지해 나머지가 한두 글자씩 꺾이지 않게 한다. | [`test_docx_table_columns_fit_their_words_1013.py`](tests/test_docx_table_columns_fit_their_words_1013.py) | 2026-10-13 |
| 2026-10-13 | 검색 엔진이 **0건으로 돌아와도** 다음 엔진으로 넘어간다 — 막혔을 때만이 아니라 (2026-10-13). | [`test_an_empty_engine_hands_over_to_the_next_1013.py`](tests/test_an_empty_engine_hands_over_to_the_next_1013.py) | 2026-10-13 |
| 2026-10-13 | 「만든 파일에는 값이 있는데 답에는 없다」 경고는 답이 **그 종류의 파일을 만들었다고 끝난 말로 말하면** 울리지 않는다. | [`test_an_answer_that_says_it_made_the_file_1013.py`](tests/test_an_answer_that_says_it_made_the_file_1013.py) | 2026-10-13 |
| 2026-10-13 | 이름 속의 숫자는 횟수가 아니다 — 「11번가」의 「11번」. | [`test_a_number_inside_a_name_is_not_a_count_1013.py`](tests/test_a_number_inside_a_name_is_not_a_count_1013.py) | 2026-10-13 |
| 2026-10-13 | 읽을 재료로 쓰인 형식 낱말은 만들 파일의 형식이 아니다 — 「엑셀을 읽어서 웹페이지로」. | [`test_a_format_that_is_read_is_not_the_output_1013.py`](tests/test_a_format_that_is_read_is_not_the_output_1013.py) | 2026-10-13 |
| 2026-10-13 | 접힌 **검색 결과**에는 앞쪽 몇 건의 링크가 남는다 (2026-10-13 · 밖에서 받은 가설). | [`test_a_folded_result_list_keeps_its_top_links_1013.py`](tests/test_a_folded_result_list_keeps_its_top_links_1013.py) | 2026-10-13 |
| 2026-10-12 | 도구가 모르는 모양의 블록을 조용히 버려 **빈 문서**가 「성공」으로 나가지 않는다 (2026-10-12 밤). | [`test_unknown_block_shapes_are_written_not_dropped_1012.py`](tests/test_unknown_block_shapes_are_written_not_dropped_1012.py) | 2026-10-12 |
| 2026-10-12 | 게임 팩을 처음 켠 사람의 화면 (2026-10-12). | [`test_unity_newcomer_guide_1012.py`](tests/test_unity_newcomer_guide_1012.py) | 2026-10-12 |
| 2026-10-12 | 되받기가 건 「파일을 만들 차례」를, 모델이 네 번 연달아 거스르면 거둔다 (2026-10-12 밤). | [`test_stage_guess_is_withdrawn_1012.py`](tests/test_stage_guess_is_withdrawn_1012.py) | 2026-10-12 |
| 2026-10-12 | 작은 창의 빈 자리를 쓴다 — 서버가 알려 준 프롬프트에 자리가 남았으면 예산을 넓히기도 한다 (2026-10-12 밤). | [`test_small_window_uses_its_idle_room_1012.py`](tests/test_small_window_uses_its_idle_room_1012.py) | 2026-10-12 |
| 2026-10-12 | 작은 창의 조사 판에는 「찾아서 읽고 파일로」 묶음만 싣는다 — 스위치(10-13 부터 기본 켜짐) (2026-10-12). | [`test_small_window_research_bundle_1012.py`](tests/test_small_window_research_bundle_1012.py) | 2026-10-12 |
| 2026-10-12 | 짧은 토막이 연달아 네 번이면 답 글을 그 자리에서 끊는다 (2026-10-12). | [`test_short_stutter_is_cut_1012.py`](tests/test_short_stutter_is_cut_1012.py) | 2026-10-12 |
| 2026-10-12 | 이어지는 질문에서 바로 앞 판의 답이 버려지지 않는다 (2026-10-12 저녁). | [`test_prior_answer_survives_a_small_window_1012.py`](tests/test_prior_answer_survives_a_small_window_1012.py) | 2026-10-12 |
| 2026-10-12 | 그림 읽기를 끌 수 있다 — 같은 모델 파일로 그림 부속만 뺀 이름을 만들어 올린다 (2026-10-12). | [`test_pictures_can_be_turned_off_1012.py`](tests/test_pictures_can_be_turned_off_1012.py) | 2026-10-12 |
| 2026-10-12 | 지목한 가게는 처음부터 가게로 안다 — 11번가 · G마켓 (2026-10-12 저녁). | [`test_named_shops_are_known_from_the_start_1012.py`](tests/test_named_shops_are_known_from_the_start_1012.py) | 2026-10-12 |
| 2026-10-12 | 지금 모델이 그림을 못 읽을 때 — 헛돌지 않고, 실패로 죽지 않고, 못 봤다고 말한다 (2026-10-12). | [`test_model_that_cannot_read_pictures_1012.py`](tests/test_model_that_cannot_read_pictures_1012.py) | 2026-10-12 |
| 2026-10-12 | 「첫 낱말로 다시 찾기」는 검색칸의 버릇을 확인한 사이트에서만 켜진다 (2026-10-12). | [`test_head_word_retry_only_where_checked_1012.py`](tests/test_head_word_retry_only_where_checked_1012.py) | 2026-10-12 |
| 2026-10-12 | 엑셀 표(`rows`)가 목록 대신 **글자열**로 와도 받는다 (2026-10-12 밤). | [`test_excel_rows_inside_a_string_1012.py`](tests/test_excel_rows_inside_a_string_1012.py) | 2026-10-12 |
| 2026-10-12 | 작은 창의 기억 — 버리기 전에 한 줄 (2026-10-12). | [`test_dropped_reads_keep_a_line_1012.py`](tests/test_dropped_reads_keep_a_line_1012.py) | 2026-10-12 |
| 2026-10-12 | 다른 AI 대화 사이트에 대신 묻지 않는다 — 사용자가 시켰을 때만 (2026-10-12). | [`test_does_not_ask_another_ai_1012.py`](tests/test_does_not_ask_another_ai_1012.py) | 2026-10-12 |
| 2026-10-12 | Claude Desktop 을 **닫고 → 잇고 → 다시 켜기**를 한 번에 (2026-10-12). | [`test_desktop_close_connect_reopen_1012.py`](tests/test_desktop_close_connect_reopen_1012.py) | 2026-10-12 |
| 2026-10-12 | 작은 창의 지침은 손에 맞춘다 (2026-10-12 저녁). | [`test_contract_fits_the_hands_1012.py`](tests/test_contract_fits_the_hands_1012.py) | 2026-10-12 |
| 2026-10-12 | 조사 판의 「파일을 만들 차례」는 **무언가 읽은 뒤에** 건다 (2026-10-12). | [`test_artifact_turn_waits_for_a_first_read_1012.py`](tests/test_artifact_turn_waits_for_a_first_read_1012.py) | 2026-10-12 |
| 2026-10-12 | 「파일 만들 차례」에서도 아직 안 읽은 사이트로 가는 손은 받는다 (2026-10-12). | [`test_artifact_turn_lets_unread_sites_through_1012.py`](tests/test_artifact_turn_lets_unread_sites_through_1012.py) | 2026-10-12 |
| 2026-10-12 | 되받기의 「진전 없음」은 그 사이에 새로 읽은 곳도 본다 (2026-10-12). | [`test_a_new_read_is_progress_for_pushbacks_1012.py`](tests/test_a_new_read_is_progress_for_pushbacks_1012.py) | 2026-10-12 |
| 2026-10-12 | 확인까지 끝난 문서를 또 쓰고, 그것도 확인됐으면 판을 접는다 (2026-10-12 밤). | [`test_a_finished_document_is_not_rewritten_forever_1012.py`](tests/test_a_finished_document_is_not_rewritten_forever_1012.py) | 2026-10-13 |
| 2026-10-11 | 직접 넣는 스킬팩 — 문서 폴더의 `skillpacks` 에 폴더를 넣으면 손자리가 읽는다 (2026-10-11). | [`test_user_skillpacks_1011.py`](tests/test_user_skillpacks_1011.py) | 2026-10-11 |
| 2026-10-11 | 대화 기록 예산은 **서버가 알려 준 실제 프롬프트 크기**를 따라 좁아진다 (2026-10-11). | [`test_transcript_budget_follows_the_real_prompt_1011.py`](tests/test_transcript_budget_follows_the_real_prompt_1011.py) | 2026-10-11 |
| 2026-10-11 | 같은 상품을 가게마다 찾은 표 — 줄은 **주소가 가리키는 가게**로 제 페이지와 묶인다 (2026-10-11). | [`test_same_product_rows_bind_by_shop_1011.py`](tests/test_same_product_rows_bind_by_shop_1011.py) | 2026-10-11 |
| 2026-10-11 | 줄의 값은 **값 칸**에서 읽는다 — 풀어 쓴 칸(비고) 속의 금액은 그 줄의 가격이 아니다 (2026-10-11). | [`test_row_value_reads_value_cells_1011.py`](tests/test_row_value_reads_value_cells_1011.py) | 2026-10-11 |
| 2026-10-11 | 다나와 · 11번가 · G마켓 상품 페이지의 값은 **도구가** 읽는다 — 가게별 값 규칙 (2026-10-11). | [`test_page_value_recipes_shops_1011.py`](tests/test_page_value_recipes_shops_1011.py) | 2026-10-11 |
| 2026-10-11 | 만든 화면을 눈으로 본다 — 화면 없는 크롬으로 따로 통째로 찍어 모델에게 보여 준다 (2026-10-11). | [`test_page_look_1011.py`](tests/test_page_look_1011.py) | 2026-10-11 |
| 2026-10-11 | 스킬팩은 그 일이 **어떤 일인지** 적어 올 수 있다 — 「웹을 보고 와서 정리하는 일」 (2026-10-11). | [`test_pack_declares_its_work_1011.py`](tests/test_pack_declares_its_work_1011.py) | 2026-10-11 |
| 2026-10-11 | 읽은 이름을 「읽지 않고 적은 것」이라고 하지 않는다 — 따옴표 **모양**만 다를 때 (2026-10-11). | [`test_listed_names_ignore_quote_shapes_1011.py`](tests/test_listed_names_ignore_quote_shapes_1011.py) | 2026-10-11 |
| 2026-10-11 | 답 글에 **도구를 부르는 글**이 그대로 새어 나오면 걷어 낸다 (2026-10-11). | [`test_leaked_tool_call_text_1011.py`](tests/test_leaked_tool_call_text_1011.py) | 2026-10-11 |
| 2026-10-11 | 만든 화면을 계산으로 잰다 — 글자가 덮였나 · 가로로 삐져나갔나 · 그림이 깨졌나 (2026-10-11). | [`test_layout_probe_1011.py`](tests/test_layout_probe_1011.py) | 2026-10-11 |
| 2026-10-11 | 아는 비밀 값은 도구 결과에서 가린다 — 값으로 찾고, 모르는 것은 지우지 않는다 (2026-10-11). | [`test_known_secrets_1011.py`](tests/test_known_secrets_1011.py) | 2026-10-11 |
| 2026-10-11 | 읽은 페이지를 접을 때 **첫머리는 남긴다** (2026-10-11). | [`test_folded_page_keeps_its_head_1011.py`](tests/test_folded_page_keeps_its_head_1011.py) | 2026-10-11 |
| 2026-10-11 | 명령 출력과 도구 결과에서 아는 비밀 값은 가려진다 · 사본에는 지워질 빈 데이터 자리를 준다 (2026-10-11). | [`test_command_output_hides_known_secrets_1011.py`](tests/test_command_output_hides_known_secrets_1011.py) | 2026-10-11 |
| 2026-10-11 | 검사는 **무엇과 견줬는지**를 말하고, 견주지 못한 줄을 말없이 넘기지 않는다 (2026-10-11). | [`test_checker_says_what_it_compared_1011.py`](tests/test_checker_says_what_it_compared_1011.py) | 2026-10-11 |
| 2026-10-11 | 만드는 일을 잘 해 놓고 마무리 보고에서 스스로 깎아내리지 않는다 (2026-10-11). | [`test_build_job_reports_are_not_talked_down_1011.py`](tests/test_build_job_reports_are_not_talked_down_1011.py) | 2026-10-11 |
| 2026-10-10 | 손자리가 켜는 Ollama 에 서버의 대화 보관함 한도를 이 PC 메모리에 맞춰 넘긴다 (2026-10-10). | [`test_ollama_prompt_cache_1010.py`](tests/test_ollama_prompt_cache_1010.py) | 2026-10-10 |
| 2026-10-10 | 그림으로 된 본문을 읽는 동안, 지금 읽는 조각을 화면에 비춘다 (2026-10-10). | [`test_image_read_shows_the_piece_1010.py`](tests/test_image_read_shows_the_piece_1010.py) | 2026-10-10 |
| 2026-10-10 | 앱을 켠 뒤 한 번, 고정 앞부분(도구 목록 + 첫 시스템 메시지)을 데워 둔다 (2026-10-10). | [`test_front_prime_1010.py`](tests/test_front_prime_1010.py) | 2026-10-10 |
| 2026-10-09 | 창이 차기 전에 한 번에 크게 접어 대화를 작게 둔다 (2026-10-09 낮). | [`test_transcript_folds_in_steps_1009.py`](tests/test_transcript_folds_in_steps_1009.py) | 2026-10-09 |
| 2026-10-09 | 코드 판의 「보통」 생각 세기를 서버가 알아듣는 자리에 싣는다 · 셸의 `format` 오탐 · 시간 제한은 멈춘 것이 아니다 (2026-10-09 새벽). | [`test_think_level_reaches_the_server_1009.py`](tests/test_think_level_reaches_the_server_1009.py) | 2026-10-09 |
| 2026-10-09 | 시험은 임시 폴더의 DB 만 연다 — 다른 곳을 가리키면 그 자리에서 떨어진다 (2026-10-09). | [`test_tests_only_open_temp_databases_1009.py`](tests/test_tests_only_open_temp_databases_1009.py) | 2026-10-09 |
| 2026-10-09 | 생각 예산 뒤의 두 번째 호출 — 대화 틀이 생각 스위치를 앞머리에 그리는 모델이면 생각을 켠 채 부른다 (2026-10-09 새벽). | [`test_second_pass_keeps_thinking_1009.py`](tests/test_second_pass_keeps_thinking_1009.py) | 2026-10-09 |
| 2026-10-09 | 우리 숙제를 손자리에게 맡긴 판에서 나온 둘 (2026-10-09 새벽). | [`test_quoted_examples_and_relative_paths_1009.py`](tests/test_quoted_examples_and_relative_paths_1009.py) | 2026-10-09 |
| 2026-10-09 | 우리 설정은 프로세스 환경에 **두지 않는다** — 맡기기 전에 합격 시험으로 썼고(2026-10-09), 손자리가 통과시킨 뒤 여기로 옮겼다. | [`test_our_settings_stay_out_of_the_environment_1009.py`](tests/test_our_settings_stay_out_of_the_environment_1009.py) | 2026-10-09 |
| 2026-10-09 | 맡긴 코드 판은 시간이 아니라 「나아가는가」로 접는다 (2026-10-09). | [`test_not_getting_anywhere_1009.py`](tests/test_not_getting_anywhere_1009.py) | 2026-10-09 |
| 2026-10-09 | 코드 판의 읽기 관문은 횟수가 아니라 「같은 것을 또 보는가」로 건다 · 손을 좁혀도 보내는 목록은 그대로 (2026-10-09 새벽). | [`test_look_gate_reads_circles_not_counts_1009.py`](tests/test_look_gate_reads_circles_not_counts_1009.py) | 2026-10-09 |
| 2026-10-09 | 「그림자 기록」의 시험 — 맡기기 **전에** 합격 시험으로 썼고(2026-10-09), 손자리가 통과시킨 뒤 여기로 옮겼다. | [`test_intent_shadow_1009.py`](tests/test_intent_shadow_1009.py) | 2026-10-09 |
| 2026-10-09 | `prepare` 가 만든 작업 자리는 일이 끝나도 남는다 — 오래된 것만 **목록으로** 보여 준다 (2026-10-09). | [`test_delegated_leftovers_1009.py`](tests/test_delegated_leftovers_1009.py) | 2026-10-09 |
| 2026-10-09 | 맡긴 코드 판은 사람의 요청에 자리를 비켜 준다 (2026-10-09). | [`test_delegated_job_yields_to_a_person_1009.py`](tests/test_delegated_job_yields_to_a_person_1009.py) | 2026-10-09 |
| 2026-10-09 | 맡긴 판은 모델이 **생각을 흘려보내는 도중에도** 사람에게 비켜 준다 (2026-10-09 저녁 · 대표 결정). | [`test_delegated_job_steps_aside_mid_thinking_1009.py`](tests/test_delegated_job_steps_aside_mid_thinking_1009.py) | 2026-10-09 |
| 2026-10-09 | 바깥 AI 가 맡긴 코드 일은 그 저장소의 **새 가지**에서 한다 (2026-10-09). | [`test_delegated_branch_1009.py`](tests/test_delegated_branch_1009.py) | 2026-10-09 |
| 2026-10-09 | 바깥 AI 가 코드 일을 맡기며 준 「확인 명령」이 끝을 가른다 (2026-10-09). | [`test_declared_check_ends_the_job_1009.py`](tests/test_declared_check_ends_the_job_1009.py) | 2026-10-09 |
| 2026-10-09 | 손자리가 실행하는 명령은 손자리 자신을 바꾸지 못한다 — 「셸 명령 자동 실행」이 켜져 있어도 (2026-10-09). | [`test_commands_do_not_change_our_own_install_1009.py`](tests/test_commands_do_not_change_our_own_install_1009.py) | 2026-10-09 |
| 2026-10-09 | 합격 시험 — agent.py 를 동작 그대로 줄인다. 맡기기 전에 썼다(2026-10-09). | [`test_agent_is_smaller_1009.py`](tests/test_agent_is_smaller_1009.py) | 2026-10-09 |
| 2026-10-08 | 읽은 개수 경고는 계획의 판정을 그대로 받는다 (2026-10-08 전수조사 4-6). | [`test_the_read_count_warning_follows_the_plan_1008.py`](tests/test_the_read_count_warning_follows_the_plan_1008.py) | 2026-10-08 |
| 2026-10-08 | 화면에서 본 줄에는 「근거가 약하다」고 하지 않는다 · 제목 속 낱말을 사이트 이름으로 배우지 않는다 (2026-10-08). | [`test_rows_seen_on_screen_and_site_names_1008.py`](tests/test_rows_seen_on_screen_and_site_names_1008.py) | 2026-10-08 |
| 2026-10-08 | 그림 읽는 부속이 없는 모델에는, 목록이 정해 준 부속을 따로 받아 붙인다 (2026-10-08). | [`test_projector_is_attached_when_the_catalog_says_so_1008.py`](tests/test_projector_is_attached_when_the_catalog_says_so_1008.py) | 2026-10-08 |
| 2026-10-08 | 도구 설명이 붙여 준 이름표(`tests`·`lint`…)로 불러도 그 명령을 돌린다 (2026-10-08). | [`test_project_command_labels_are_accepted_1008.py`](tests/test_project_command_labels_are_accepted_1008.py) | 2026-10-08 |
| 2026-10-08 | 쓰기 금지 범위는 끝 글자가 아니라 요청 자체로 · 행위 규칙은 한 문장 안에서 (2026-10-08 전수조사 3-4). | [`test_prohibition_scope_and_action_sentences_1008.py`](tests/test_prohibition_scope_and_action_sentences_1008.py) | 2026-10-08 |
| 2026-10-08 | 사람 수는 개수 요구가 아니고, 소감 한마디는 앞 요청을 물려받지 않는다 (2026-10-08). | [`test_party_size_and_remarks_do_not_become_requirements_1008.py`](tests/test_party_size_and_remarks_do_not_become_requirements_1008.py) | 2026-10-08 |
| 2026-10-08 | 우리 꼬리 뒤에 「만든 파일:」이 붙으면 꼬리가 모델에게 그대로 갔다 (2026-10-08 전수조사 3-3). | [`test_our_tail_behind_a_fact_trailer_1008.py`](tests/test_our_tail_behind_a_fact_trailer_1008.py) | 2026-10-08 |
| 2026-10-08 | 미리 내다보기(MTP)는 이 PC 에서 재 보고 빠를 때만 켠다 (2026-10-08). | [`test_mtp_is_measured_before_it_is_turned_on_1008.py`](tests/test_mtp_is_measured_before_it_is_turned_on_1008.py) | 2026-10-08 |
| 2026-10-08 | 화면을 다시 본 걸음은 자율 걸음 상한을 덜 쓴다 (2026-10-08). | [`test_looking_does_not_use_up_the_step_cap_1008.py`](tests/test_looking_does_not_use_up_the_step_cap_1008.py) | 2026-10-08 |
| 2026-10-08 | 번호 목록·불릿으로 낸 답도 「화면에서 본 줄」로 센다 (2026-10-08 전수조사 3-2). | [`test_list_items_seen_on_screen_1008.py`](tests/test_list_items_seen_on_screen_1008.py) | 2026-10-08 |
| 2026-10-08 | 바깥 AI 의 과제 방·측정 방에서 배운 것은 사람에 관한 사실이 아니다 (2026-10-08 전수조사 3-7). | [`test_facts_from_task_rooms_are_not_the_persons_1008.py`](tests/test_facts_from_task_rooms_are_not_the_persons_1008.py) | 2026-10-08 |
| 2026-10-08 | 「읽지 않고 적은 것」 경고가 헛짚던 두 모양 (2026-10-08). | [`test_entity_warning_skips_attributes_and_local_only_1008.py`](tests/test_entity_warning_skips_attributes_and_local_only_1008.py) | 2026-10-08 |
| 2026-10-08 | 한국어 쪽에서 고친 병이 영어 쪽에 그대로 남아 있던 셋 (2026-10-08 전수조사 3-6). | [`test_english_twins_of_korean_fixes_1008.py`](tests/test_english_twins_of_korean_fixes_1008.py) | 2026-10-08 |
| 2026-10-08 | 목록 과제 세 판(2026-10-08 실기)에서 나온 넷. | [`test_declined_detail_and_lost_rows_1008.py`](tests/test_declined_detail_and_lost_rows_1008.py) | 2026-10-08 |
| 2026-10-08 | 시간 제한에 걸린 명령은 **그 아래 프로세스까지** 끝내고, 일꾼을 붙잡지 않는다 (2026-10-08). | [`test_a_timed_out_command_frees_the_worker_1008.py`](tests/test_a_timed_out_command_frees_the_worker_1008.py) | 2026-10-08 |
| 2026-10-08 | 검색 목록 화면을 읽은 것은 「직접 열어 읽은 N개」가 아니다 (2026-10-08 실기 — 사람인 판). | [`test_a_search_listing_is_not_one_of_the_details_1008.py`](tests/test_a_search_listing_is_not_one_of_the_details_1008.py) | 2026-10-09 |
| 2026-10-08 | 「○○ 밖의 파일은 건드리지 마라」는 ○○ 을 고치라는 판이다 (2026-10-08). | [`test_a_prohibition_that_leaves_something_to_edit_1008.py`](tests/test_a_prohibition_that_leaves_something_to_edit_1008.py) | 2026-10-08 |
| 2026-10-08 | 연 바로 다음에 그 사이트를 읽었으면 읽은 것이다 (2026-10-08 전수조사 3-2). | [`test_a_page_read_right_after_opening_is_read_1008.py`](tests/test_a_page_read_right_after_opening_is_read_1008.py) | 2026-10-08 |
| 2026-10-08 | 지목한 이름이 우리가 아는 사이트면 에이전트로 간다 (2026-10-08). | [`test_a_known_site_named_goes_to_the_agent_1008.py`](tests/test_a_known_site_named_goes_to_the_agent_1008.py) | 2026-10-08 |
| 2026-10-08 | 검증 명령에 폴더 대신 파일 경로를 주면, 그 파일이 든 폴더에서 돌린다 (2026-10-08). | [`test_a_file_path_runs_the_command_in_its_folder_1008.py`](tests/test_a_file_path_runs_the_command_in_its_folder_1008.py) | 2026-10-08 |
| 2026-10-08 | 브라우저를 쓰지 않은 판은 브라우저에 떠 있는 로그인 화면 때문에 멈추지 않는다 (2026-10-08). | [`test_a_failed_local_tool_does_not_read_the_browser_wall_1008.py`](tests/test_a_failed_local_tool_does_not_read_the_browser_wall_1008.py) | 2026-10-08 |
| 2026-10-08 | 같은 폴더 이름이 두 번 겹친 경로는 실제로 있는 쪽으로 바로잡는다 (2026-10-08). | [`test_a_doubled_folder_name_is_undoubled_1008.py`](tests/test_a_doubled_folder_name_is_undoubled_1008.py) | 2026-10-08 |
| 2026-10-08 | 자백은 모델의 글에서만 읽는다 — 우리가 붙인 경고는 읽지 않는다 (2026-10-08 전수조사 4-1). | [`test_a_confession_is_read_from_the_models_words_1008.py`](tests/test_a_confession_is_read_from_the_models_words_1008.py) | 2026-10-08 |
| 2026-10-08 | 코드 이야기의 「주석」은 각주가 아니다 (2026-10-08). | [`test_a_comment_in_code_is_not_a_footnote_1008.py`](tests/test_a_comment_in_code_is_not_a_footnote_1008.py) | 2026-10-08 |
| 2026-10-07 | 본 창이 시킨 판의 답은 **판 밖에서** 칠한다 — 연출 때문에 판이 늦게 끝나지 않게 (2026-10-07). | [`test_the_typing_effect_runs_apart_from_the_job_1007.py`](tests/test_the_typing_effect_runs_apart_from_the_job_1007.py) | 2026-10-08 |
| 2026-10-07 | 검사는 이 PC 에서 재생 중인 미디어를 멈추지 않는다 (2026-10-07 — 회귀 출력의 `0x8001010e` 20번을 따라가서). | [`test_tests_leave_playing_media_alone_1007.py`](tests/test_tests_leave_playing_media_alone_1007.py) | 2026-10-07 |
| 2026-10-07 | 검사가 띄우는 브라우저는 그래픽카드를 쓰지 않는다 (2026-10-07 — `conftest.py` 의 같은 이름 고정물). | [`test_test_browsers_leave_the_gpu_alone_1007.py`](tests/test_test_browsers_leave_the_gpu_alone_1007.py) | 2026-10-07 |
| 2026-10-07 | 작은 폴더는 색인 결과를 따로 붙이지 않는다 (2026-10-07 코딩 사다리 L6). | [`test_small_folders_skip_the_index_step_1007.py`](tests/test_small_folders_skip_the_index_step_1007.py) | 2026-10-07 |
| 2026-10-07 | 화면에서 해 달라는 말은 손이 있는 길로 · 사람이 대화에서 준 숫자는 근거다 (2026-10-07 대표 실사용). | [`test_screen_actions_and_given_numbers_1007.py`](tests/test_screen_actions_and_given_numbers_1007.py) | 2026-10-07 |
| 2026-10-07 | 같은 이름의 칸이 둘 이상이면 **어느 묶음의 칸인지**가 같이 온다 (2026-10-07 폼 벤치 과제 J · 고치기 전 3판 중 1판). | [`test_same_named_fields_carry_their_group_1007.py`](tests/test_same_named_fields_carry_their_group_1007.py) | 2026-10-07 |
| 2026-10-07 | 어려운 코딩 과제에서 나온 둘 (2026-10-07 사다리 L7·L8, 3판씩). | [`test_review_scratch_and_family_budget_1007.py`](tests/test_review_scratch_and_family_budget_1007.py) | 2026-10-08 |
| 2026-10-07 | 조사 판에도 **같은 도구 목록**을 보낸다 — 갈래 밖의 손은 부르면 되돌려 보낸다 (2026-10-07 서버 기록). | [`test_research_jobs_see_the_same_tool_list_1007.py`](tests/test_research_jobs_see_the_same_tool_list_1007.py) | 2026-10-07 |
| 2026-10-07 | 판마다 바뀌는 것은 시스템 메시지가 아니라 **요청 메시지 앞**에 싣는다 (2026-10-07 코딩 사다리 L6 기준선). | [`test_per_job_context_rides_on_the_request_1007.py`](tests/test_per_job_context_rides_on_the_request_1007.py) | 2026-10-07 |
| 2026-10-07 | 붙여넣은 글의 숫자는 시킨 개수가 아니다 · 화면의 폼에 넣는 것은 파일 만들기가 아니다 (2026-10-07 대표 실사용). | [`test_pasted_text_is_not_an_instruction_1007.py`](tests/test_pasted_text_is_not_an_instruction_1007.py) | 2026-10-07 |
| 2026-10-07 | 페이지 데이터 도구는 **다 받은 응답만** 읽는다 (2026-10-07 폼 벤치 과제 F 의 한 판). | [`test_page_data_reads_only_finished_responses_1007.py`](tests/test_page_data_reads_only_finished_responses_1007.py) | 2026-10-07 |
| 2026-10-07 | 모델 호출 한 번의 벽시계 시간이 판 기록에 남는다 (2026-10-07 코딩 사다리 기준선). | [`test_model_call_wall_time_is_recorded_1007.py`](tests/test_model_call_wall_time_is_recorded_1007.py) | 2026-10-07 |
| 2026-10-07 | 폼을 다루는 화면에서 브라우저 도구가 넘어진 다섯 자리 (2026-10-07 대표 실사용 · 진짜 크로미움 + 가짜). | [`test_form_operation_tools_1007.py`](tests/test_form_operation_tools_1007.py) | 2026-10-07 |
| 2026-10-07 | 폼 벤치 과제 G·H·I 에서 나온 도구 버그 셋 (2026-10-07 · 고치기 전 3판씩: 자동완성 1/3 · 달력 0/3 · 파일 올리기 0/3). | [`test_form_elements_bench_fj_1007.py`](tests/test_form_elements_bench_fj_1007.py) | 2026-10-07 |
| 2026-10-07 | 바깥 AI 가 맡긴 판은 답을 「스르륵」 칠하느라 끝을 늦추지 않는다 (2026-10-07 코딩 사다리). | [`test_delegated_jobs_do_not_wait_on_the_typing_effect_1007.py`](tests/test_delegated_jobs_do_not_wait_on_the_typing_effect_1007.py) | 2026-10-07 |
| 2026-10-07 | 화면이 자주 묻는 가벼운 길은, 앞 물음이 띄운 느린 일이 아직 돌면 **겹쳐 돌지 않는다** (2026-10-07). | [`test_checks_do_not_pile_up_1007.py`](tests/test_checks_do_not_pile_up_1007.py) | 2026-10-07 |
| 2026-10-07 | 대화·라우터 호출도 **턴마다 바뀌는 것**(시각·스킬 메모)을 시스템 글이 아니라 요청문 앞에 싣는다 (2026-10-07). | [`test_chat_turns_keep_the_system_message_fixed_1007.py`](tests/test_chat_turns_keep_the_system_message_fixed_1007.py) | 2026-10-07 |
| 2026-10-07 | 열어 달라고 한 주소가 다른 주소로 넘어가도, 그 주소는 「연 주소」다 (2026-10-07 6차 굽기 전 실기 확인에서 나온 것). | [`test_asked_address_counts_as_opened_1007.py`](tests/test_asked_address_counts_as_opened_1007.py) | 2026-10-07 |
| 2026-10-07 | 요청이 주소를 적어 줬으면, 그 판이 시작하기 전부터 열려 있던 **다른 사이트의 탭**으로 넘어가지 않는다 (2026-10-07 폼 벤치 과제 J). | [`test_a_named_address_keeps_the_job_off_other_sites_tabs_1007.py`](tests/test_a_named_address_keeps_the_job_off_other_sites_tabs_1007.py) | 2026-10-07 |
| 2026-10-07 | 폼을 채우는 도중은 끝이 아니다 — 폼 벤치 넷째 판이 찾은 셋 (2026-10-07, Gemma 4 26B · 과제 E 0/3 · 과제 A 1/3). | [`test_a_form_in_progress_is_not_done_1007.py`](tests/test_a_form_in_progress_is_not_done_1007.py) | 2026-10-07 |
| 2026-10-05 | 믿는 태그는 글이 가장 많은 것을 · 그림으로 된 본문은 읽어서 붙인다 (2026-10-05). | [`test_trusted_tag_and_image_body_1005.py`](tests/test_trusted_tag_and_image_body_1005.py) | 2026-10-05 |
| 2026-10-05 | 영어 화면의 진행 줄에 「browser_extract 실행 중」이 그대로 나갔다 (2026-10-05, 스토어용 영어 장면을 찍다가). | [`test_tool_labels_in_english_1005.py`](tests/test_tool_labels_in_english_1005.py) | 2026-10-05 |
| 2026-10-05 | 판정기가 못 가르는 사이트의 **상세 주소 표식** (2026-10-05 9B 판 — arXiv 목록 · 네이버 뉴스 섹션). | [`test_result_links_1005.py`](tests/test_result_links_1005.py) | 2026-10-05 |
| 2026-10-05 | 같은 것이 그대로 가리고 있는 자리를 또 누르면 기다리지 않고 바로 알린다 (2026-10-05 사다리 L2). | [`test_repeat_blocked_click_1005.py`](tests/test_repeat_blocked_click_1005.py) | 2026-10-05 |
| 2026-10-05 | 주소를 직접 쳐서 다른 곳으로 간 뒤에는, 앞 목록의 순위를 추측해서 열지 않는다 (2026-10-05 AWS 영어 윈도우, c3c1b051). | [`test_rank_after_leaving_by_address_1005.py`](tests/test_rank_after_leaving_by_address_1005.py) | 2026-10-05 |
| 2026-10-05 | 우리가 답 끝에 덧붙인 경고·대조표는 다음 턴의 모델에게 들어가지 않는다 (2026-10-05 대표 실사용, 전략 대화 방). | [`test_our_notes_are_not_fed_back_1005.py`](tests/test_our_notes_are_not_fed_back_1005.py) | 2026-10-05 |
| 2026-10-05 | 만든 파일을 띄울 때 — 여는 프로그램이 없는 PC 에서 오류 창이 뜨지 않는다 (2026-10-05 AWS 영어 윈도우 새 PC). | [`test_open_made_file_without_an_app_1005.py`](tests/test_open_made_file_without_an_app_1005.py) | 2026-10-05 |
| 2026-10-05 | Ollama 켜기는 한 번에 한 사람만 — 설치 직후 「설치하지 못했습니다 (serve_exited:1)」가 뜬 까닭 (2026-10-05). | [`test_ollama_serve_one_at_a_time_1005.py`](tests/test_ollama_serve_one_at_a_time_1005.py) | 2026-10-05 |
| 2026-10-05 | 구글이 목적지를 숨긴 링크(`/goto?url=암호화`)로 결과를 줄 때도 결과를 읽는다 (2026-10-05). | [`test_google_hides_the_destination_1005.py`](tests/test_google_hides_the_destination_1005.py) | 2026-10-05 |
| 2026-10-05 | 영어로 시킨 판은 생각·중계까지 영어로 남는다 (2026-10-05 AWS 영어 윈도우 · Tesla T4 · qwen3.5:9b). | [`test_english_run_stays_english_1005.py`](tests/test_english_run_stays_english_1005.py) | 2026-10-05 |
| 2026-10-05 | 영어로 시킨 판에서 모델이 검색어를 한국어로 옮겨 넣으면 한 번 돌려보낸다 (2026-10-05 9B · 영어 화면). | [`test_english_request_korean_query_1005.py`](tests/test_english_request_korean_query_1005.py) | 2026-10-05 |
| 2026-10-05 | 스토어용 영어 장면을 찍다가 나온 것 (2026-10-05 아침, 가짜 홈 · 추천 모델 Gemma 4 26B · 판 9cae577f). | [`test_english_capture_run_1005.py`](tests/test_english_capture_run_1005.py) | 2026-10-05 |
| 2026-10-05 | 「이어서 해줘」는 덜 끝난 앞 판을 잇는다 · 파일 찾기는 얕은 곳부터 보고 다 못 봤으면 그렇게 말한다 (2026-10-05 실사용). | [`test_continue_and_find_files_1005.py`](tests/test_continue_and_find_files_1005.py) | 2026-10-05 |
| 2026-10-05 | 링크를 눌러 넘어간 뒤 **사라진 요소를 16초 기다렸다** (2026-10-05 AWS 영어 윈도우 첫 실행). | [`test_click_does_not_wait_on_a_vanished_element_1005.py`](tests/test_click_does_not_wait_on_a_vanished_element_1005.py) | 2026-10-05 |
| 2026-10-05 | 표 블록의 대괄호 개수가 틀려도 줄은 건진다 (2026-10-05 9B arXiv 판 d3a87ec6). | [`test_broken_table_brackets_1005.py`](tests/test_broken_table_brackets_1005.py) | 2026-10-05 |
| 2026-10-05 | 된 판을 「못 했다」고 말한 자리 셋 (2026-10-05 AWS 영어 윈도우 · Tesla T4 · qwen3.5:9b). | [`test_aws_first_run_judgements_1005.py`](tests/test_aws_first_run_judgements_1005.py) | 2026-10-05 |
| 2026-10-04 | 끝내지 못한 판(실패·멈춤)도 대화에 남는다 (2026-10-04 새벽). | [`test_unfinished_turn_recorded_1004.py`](tests/test_unfinished_turn_recorded_1004.py) | 2026-10-04 |
| 2026-10-04 | 도구 목록 「빠진 손」 전수조사(`docs/도구목록_빠진손_전수조사_1004.ko.md`)에서 고친 것들 (2026-10-04). | [`test_tool_hands_audit_1004.py`](tests/test_tool_hands_audit_1004.py) | 2026-10-04 |
| 2026-10-04 | 끼어든 한자 고치기 — 일하면서 하는 말에도, 영어 화면에도 (2026-10-04 사다리 L2 화면 「원격 관測 시작」). | [`test_stray_han_1004.py`](tests/test_stray_han_1004.py) | 2026-10-04 |
| 2026-10-04 | 도구 목록이 붙은 호출에서 답 글이 길어지며 속도가 무너지면, 끊고 도구 없이 다시 받는다 (2026-10-04 실측). | [`test_slow_content_under_tools_1004.py`](tests/test_slow_content_under_tools_1004.py) | 2026-10-04 |
| 2026-10-04 | 시트 이름에 엑셀이 못 받는 글자가 있어도 쓰기는 된다 (2026-10-04 허깅페이스 판 3ad09518). | [`test_sheet_titles_are_made_valid_1004.py`](tests/test_sheet_titles_are_made_valid_1004.py) | 2026-10-04 |
| 2026-10-04 | 검색·목록 화면의 주소는 「같은 종류 페이지의 모양」으로 기억하지도 알려 주지도 않는다 (2026-10-04 실전 판 574826ac). | [`test_search_address_not_remembered_1004.py`](tests/test_search_address_not_remembered_1004.py) | 2026-10-04 |
| 2026-10-04 | 상자가 내보낸 파일도 「이 판이 만든 것」이다 — 다시 만들면 덮어쓴다 (2026-10-04 레딧 기준선 판 b79871c7). | [`test_sandbox_overwrites_own_file_1004.py`](tests/test_sandbox_overwrites_own_file_1004.py) | 2026-10-04 |
| 2026-10-04 | 줄의 숫자가 그 줄의 페이지가 아니라 **다른 줄의 페이지**에서 왔으면 잡고, 맞게 썼던 줄이면 되돌린다 (2026-10-04 허깅페이스 판 5749ff16). | [`test_row_numbers_from_another_rows_page_1004.py`](tests/test_row_numbers_from_another_rows_page_1004.py) | 2026-10-04 |
| 2026-10-04 | 답 표의 줄에 적은 금액·시킨 근무형태를 **그 줄의 페이지**와 맞춘다 · 빼 놓은 것에 경고하지 않는다 · 날짜 옆의 「내일」 (2026-10-04 채용 공고 조사 판 788ef850). | [`test_row_facts_vs_page_1004.py`](tests/test_row_facts_vs_page_1004.py) | 2026-10-04 |
| 2026-10-04 | 검사가 「먼저 열어서 읽어라」고 한 주소는 열 수 있어야 한다 · 엑셀 고치기는 엉뚱한 시트에 조용히 쓰지 않는다 (2026-10-04). | [`test_repair_read_and_sheet_1004.py`](tests/test_repair_read_and_sheet_1004.py) | 2026-10-04 |
| 2026-10-04 | 레딧 글 목록을 읽으면 글마다 제목·댓글 수·추천 수·지난 시간·**진짜 글 주소**가 같이 온다 (2026-10-04). | [`test_reddit_listing_1004.py`](tests/test_reddit_listing_1004.py) | 2026-10-04 |
| 2026-10-04 | 레시피가 적어 둔 **읽을 자리**를 읽는다 — 회사 템플릿의 `<main>` 만 읽지 않는다 (2026-10-04 실전 판 e055235f). | [`test_recipe_read_places_1004.py`](tests/test_recipe_read_places_1004.py) | 2026-10-04 |
| 2026-10-04 | 레시피가 **이름**을 받아 사이트의 값으로 바꾼다 — 번호를 짐작하지 않게 (2026-10-04 실전 판 574826ac). | [`test_recipe_named_values_1004.py`](tests/test_recipe_named_values_1004.py) | 2026-10-04 |
| 2026-10-04 | 산출물 차례에서도 **방금 처음 연 페이지의 첫 읽기**는 막지 않는다 (2026-10-04 새벽 레딧 판 33cac79a). | [`test_read_opened_page_in_deliver_turn_1004.py`](tests/test_read_opened_page_in_deliver_turn_1004.py) | 2026-10-04 |
| 2026-10-04 | 페이지를 만든 코드 판은 화면 손이 열린다 (2026-10-04 도구 전수조사 2번). | [`test_page_preview_opens_midrun_1004.py`](tests/test_page_preview_opens_midrun_1004.py) | 2026-10-04 |
| 2026-10-04 | 없는 페이지(404)는 「열었다」가 아니다 · 같은 사이트에서 같은 검색어를 되풀이하면 걸린다 (2026-10-04 허깅페이스 판 56247177). | [`test_page_not_found_is_not_opened_1004.py`](tests/test_page_not_found_is_not_opened_1004.py) | 2026-10-04 |
| 2026-10-04 | 파일 이름 속 낱말은 시킨 일이 아니다 · 사이트 이름표로 묶은 규칙 표는 항목 표가 아니다 (2026-10-04 밤 판 98ae0a6b). | [`test_names_are_not_requests_1004.py`](tests/test_names_are_not_requests_1004.py) | 2026-10-05 |
| 2026-10-04 | 「로컬」은 뒤에 파일을 담는 것이 올 때만 출처다 · 출처 이름표가 틀려도 읽은 것은 센다 (2026-10-04 허깅페이스 판 5749ff16). | [`test_local_scope_allow_list_1004.py`](tests/test_local_scope_allow_list_1004.py) | 2026-10-04 |
| 2026-10-04 | 이 PC 안 페이지의 확인창은 따로 정하지 않았으면 확인으로 답한다 (2026-10-04 대표 결정, 도구 전수조사 11번). | [`test_local_page_dialog_1004.py`](tests/test_local_page_dialog_1004.py) | 2026-10-04 |
| 2026-10-04 | 사람이 「하나하나 열 필요 없다」고 한 과제 — 이름표·안내·줄 수·경고가 같은 말을 한다 (2026-10-04 레딧 기준선 판 92b3776a). | [`test_list_only_requests_1004.py`](tests/test_list_only_requests_1004.py) | 2026-10-04 |
| 2026-10-04 | 글 번호를 지어낸 주소 — 엉뚱한 글을 「열었다」고 하지 않는다 (2026-10-04 새벽, 판 df35948f). | [`test_fabricated_post_address_1004.py`](tests/test_fabricated_post_address_1004.py) | 2026-10-04 |
| 2026-10-04 | 요약은 바깥, 본문은 안쪽 틀 — 둘 다 읽는다 · 쌓인 다음 항목은 읽지 않는다 · 그림 본문은 그림이라고 말한다 (2026-10-04 채용 공고 조사 판 788ef850). | [`test_extract_reads_the_body_frame_1004.py`](tests/test_extract_reads_the_body_frame_1004.py) | 2026-10-04 |
| 2026-10-04 | 머리줄이 있는 표는 줄마다 한 줄로, 칸마다 머리말을 붙여 읽는다 (2026-10-04 허깅페이스 판 5749ff16). | [`test_extract_labels_table_cells_1004.py`](tests/test_extract_labels_table_cells_1004.py) | 2026-10-04 |
| 2026-10-04 | 임베딩 서버가 없는 PC 에서 색인이 부를 때마다 2초를 버리지 않는다 (2026-10-04). | [`test_embed_server_absent_1004.py`](tests/test_embed_server_absent_1004.py) | 2026-10-04 |
| 2026-10-04 | 닫을 수 있는 로그인 **팝업**은 사람 문이 아니다 — 단, 닫아도 되는 때에만 (2026-10-04, 진짜 크로미움). | [`test_dismissible_login_popup_1004.py`](tests/test_dismissible_login_popup_1004.py) | 2026-10-04 |
| 2026-10-04 | 한 번에 걸음 상한을 넘긴 판도 접기 전에 **파일 쓸 차례**를 받는다 (2026-10-04 레딧 판 5043f5bb). | [`test_deliver_turn_after_batch_boundary_1004.py`](tests/test_deliver_turn_after_batch_boundary_1004.py) | 2026-10-04 |
| 2026-10-04 | 폴더 지우기 — 이 판이 만든 폴더와 캐시 폴더만 (2026-10-04 대표 결정). | [`test_delete_own_folder_1004.py`](tests/test_delete_own_folder_1004.py) | 2026-10-04 |
| 2026-10-04 | 요청 동사에 바로 붙은 개수가 요구다 (2026-10-04 새벽 레딧 판 df35948f·33cac79a·93f08e95). | [`test_count_target_request_verb_1004.py`](tests/test_count_target_request_verb_1004.py) | 2026-10-04 |
| 2026-10-04 | 답 글이 같은 토막을 되풀이하면 상한까지 기다리지 않고 끊는다 (2026-10-04 허깅페이스 판 56247177). | [`test_content_loop_is_cut_1004.py`](tests/test_content_loop_is_cut_1004.py) | 2026-10-04 |
| 2026-10-04 | 코드 모드 군살 빼기 (2026-10-04 · 헤르메스 전수조사 `docs/헤르메스_코딩하네스_전수조사_1003.ko.md`). | [`test_code_mode_lean_1004.py`](tests/test_code_mode_lean_1004.py) | 2026-10-04 |
| 2026-10-04 | 짧은 답의 **어느 문장이든** 앞으로 할 일이고 결과를 말한 문장이 없으면 예고다 (2026-10-04 실전 판 e055235f). | [`test_announce_without_a_result_1004.py`](tests/test_announce_without_a_result_1004.py) | 2026-10-04 |
| 2026-10-04 | 「브라우저」를 이야깃거리로 말한 것은 가서 보라는 말이 아니다 (2026-10-04, A6 — 10-03 21:56 2ea375c4). | [`test_a_mention_is_not_a_request_to_look_1004.py`](tests/test_a_mention_is_not_a_request_to_look_1004.py) | 2026-10-04 |
| 2026-10-03 | 22시 레딧 예약 판(2026-10-03 5fa9b74c)에서 나온 것. | [`test_reddit_comments_and_repeats_1003.py`](tests/test_reddit_comments_and_repeats_1003.py) | 2026-10-03 |
| 2026-10-03 | 2026-10-03 영어 벤치 셋(GitHub 트렌딩 · arXiv · python 3.13)에서 나온 것. | [`test_english_bench_1003.py`](tests/test_english_bench_1003.py) | 2026-10-03 |
| 2026-10-03 | 화면 조작 묶음 B (2026-10-03, Browser Use 조작 방식 조사 · Online-Mind2Web 실패 판). | [`test_browser_manipulation_1003.py`](tests/test_browser_manipulation_1003.py) | 2026-10-03 |
| 2026-09-28 | 09-28 새벽 데모에서 잡은 셋. | [`test_demo_fixes_0928.py`](tests/test_demo_fixes_0928.py) | 2026-09-28 |
| 2026-09-27 | 09-27 밤 실사용에서 잡은 셋. | [`test_steer_answer_and_model_loads_0927.py`](tests/test_steer_answer_and_model_loads_0927.py) | 2026-09-28 |
