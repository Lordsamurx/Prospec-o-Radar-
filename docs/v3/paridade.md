# Paridade com o protótipo

Os 19 itens da seção 3 do prompt da v3. Cada um com o teste que cobre.
Testes em `backend/tests/` (rodar: `python scripts/dev.py test`) e no navegador em `backend/tests/e2e/` (`python scripts/dev.py e2e`).

Situação em 10/11/2026: **332 testes de unidade e integração e 87 no navegador passando** no ambiente de nuvem (Linux, Python 3.13, Chromium). Não rodados no Windows.

| # | Item | Situação | Testes |
|---|------|----------|--------|
| 1 | Busca por nicho + cidade/bairro (+ raio), carregamento animado, provedor por `PLACES_PROVIDER` | ✅ | `test_api::test_busca_cria_leads_e_repetir_nao_duplica`, `test_busca_por_pino_no_mapa`, `test_busca_invalida`, `test_providers::test_provedor_padrao_e_osm`, `e2e/test_fluxo::test_fluxo_completo` |
| 2 | Fictícios de BH em vários nichos; comando `seed` | ✅ (72 negócios, 39 nichos) | `test_importer::test_seed_e_idempotente_e_marca_ficticios`, `test_filters::test_seed_spreads_over_many_sectors`, `test_providers::test_ficticios_sao_marcados` |
| 3 | OSM: bairro (1,5 km) ou cidade; nicho → tags; fora da lista procura no nome; outros servidores; atribuição | ✅ com HTTP falso | `test_providers::test_osm_consulta_por_bairro_e_atribuicao`, `test_osm_cidade_inteira_usa_area`, `test_osm_nicho_fora_da_lista_busca_pelo_nome`, `test_osm_tenta_o_proximo_servidor`, `test_osm_todos_ocupados_pede_pausa` |
| 4 | Google: field mask, `includedType`, paginação, cache sem maiúsculas/acentos, falha também conta | ✅ com HTTP falso | `test_providers::test_google_field_mask_tipo_e_idioma`, `test_google_pagina_ate_3_e_conta_cada_pagina`, `test_cache_ignora_maiusculas_e_acentos`, `test_requisicao_que_falhou_conta_na_cota`, `test_google_erro_conta_e_nao_vaza_a_chave` |
| 5 | Upsert por `place_id`, sem duplicar | ✅ | `test_providers::test_upsert_nao_duplica_e_preserva_o_que_e_do_samuel`, `test_api::test_busca_cria_leads_e_repetir_nao_duplica` |
| 6 | Lista com filtros sem recarregar, chips, barra Nicho/Site/Nota, "Mais filtros" pela URL | ✅ | `test_filters::test_each_filter`, `test_combined_filters_narrow_the_count`, `test_query_roundtrip_and_chips`, `test_api::test_lista_filtra_e_ordena`, `test_lista_htmx_devolve_so_o_fragmento`, `e2e/test_fluxo::test_filtros_atualizam_sem_recarregar` |
| 7 | Nome abre o Maps em nova aba; WhatsApp só celular; Ver site; Gerar amostra | ✅ | `test_api::test_nome_abre_o_maps_em_nova_aba`, `test_normalize::test_whatsapp_link_only_for_mobile_and_encodes_text`, `test_sites_outreach::test_rascunho_nos_4_canais` |
| 8 | Nota A/B/C com motivo, manual prevalece, regras do docs/06 inclusive OSM | ✅ | `test_diagnose_scoring::test_score_rules`, `test_score_manual_wins_and_shows_automatic`, `test_score_osm_without_check_is_b_and_asks_to_check_maps`, `test_api::test_nota_manual_e_volta_para_automatica` |
| 9 | Drawer: dados, status, nota, amostra, rascunho com copiar, histórico, "não contatar"; foco preso | ✅ | `test_api::test_drawer_mostra_diagnostico_e_servicos`, `e2e/test_fluxo::test_fluxo_completo`, `test_teclado_lista_drawer_e_paleta`, `e2e/test_acessibilidade::test_drawer_acessivel` |
| 10 | Funil por etapa e nicho; kanban arrastar e seletor; evento com data de Brasília | ✅ (arrastar testado à mão em tela, não em teste automático) | `test_api::test_funil_conta_por_etapa_e_por_nicho`, `test_etapa_pelo_kanban_devolve_o_cartao`, `test_mudar_etapa_grava_evento_e_proxima_acao`, `test_funnel::test_change_status_records_event_and_lost_reason` |
| 11 | Amostra estática em `data/previews/<slug>/`, `noindex`, `robots.txt`, faixa "Amostra", iframe isolado, `/previews/<slug>/` | ✅ 5 modelos | `test_sites_outreach::test_cada_modelo_gera_amostra_com_noindex[*]`, `test_amostra_escapa_o_nome`, `e2e/test_acessibilidade::test_amostra_acessivel_e_responsiva[*]` |
| 12 | Rascunho com gancho por nicho e link da amostra; copiar | ✅ | `test_sites_outreach::test_mensagem_usa_a_amostra_e_o_perfil_do_vendedor`, `test_rascunho_nao_envia_e_nao_muda_a_etapa`, `e2e/test_fluxo::test_fluxo_completo` (confere a área de transferência) |
| 13 | CSV sem injeção de fórmula | ✅ | `test_api::test_csv_abre_no_excel_e_nao_vira_formula`, `test_normalize::test_csv_cell_blocks_formula` |
| 14 | Senha protege tudo menos `/health` e `/previews`; `render.yaml` e doc do Render | ✅ (Render não publicado de verdade) | `test_security::test_senha_protege_tudo[*]`, `test_senha_protege_as_acoes`, `test_saude_e_amostras_ficam_abertas`; doc: `docs/v3/publicar-render.md` |
| 15 | CSRF; filtro inválido não zera os outros; datas de Brasília | ✅ | `test_security::test_csrf_bloqueia_outra_origem`, `test_filters::test_invalid_filter_does_not_reset_the_others`, `test_api::test_o_dia_vira_a_meia_noite_de_brasilia`, `test_cota_so_conta_o_dia_de_brasilia` |
| 16 | JSON com `?format=json` ou `Accept: application/json` | ✅ | `test_api::test_tudo_tem_json[*]` e quase todos os testes de API |
| 17 | Docker e `scripts/dev.py run/test/seed/smoke` sem `make` | ⚠️ `dev.py` testado; **imagem Docker não construída** (Docker Hub recusou o download da imagem base: erro 429) | `scripts/smoke.py` (rodado: SMOKE OK) |
| 18 | Acessibilidade: contraste AA, teclado, menos movimento, responsivo | ✅ axe sem violações nas 10 telas, claro e escuro, computador e celular | `e2e/test_acessibilidade::*` (alvos de toque, foco visível, sem rolagem lateral) |
| 19 | `import-v1`: leads, eventos, notas manuais, "não contatar", amostras, rascunhos, etapas mapeadas, fictícios marcados | ✅ testado com banco montado e com **cópia do banco real** (107 leads, 208 eventos, 4 amostras) | `test_importer::test_importa_leads_eventos_amostras_e_rascunhos`, `test_importar_duas_vezes_nao_duplica`, `test_importa_o_banco_real_do_prototipo` |

## O que é novo (seção 4) e onde está testado

| Seção | Testes |
|-------|--------|
| 4.1 Nichos e setores (12 setores, 118 nichos, YAML validado) | `test_catalog.py` |
| 4.2 Raio-X (diagnóstico) | `test_diagnose_scoring.py::test_diagnose_*` |
| 4.3 Nota, perfil digital (6) e índice de oportunidade | `test_diagnose_scoring.py::test_profile_six_types`, `test_opportunity_*` |
| 4.4 Catálogo de serviços (14, sem preço inventado, editável) | `test_catalog.py::test_services_catalog_has_14_services`, `test_settings_services.py::test_catalogo_de_servicos_sem_preco_inventado`, `test_editar_servico_preco_e_desativar` |
| 4.5 Recomendação por lead | `test_recommend_strategy.py` (uma regra por teste) |
| 4.6 Tela Serviços por categoria | `test_settings_services.py::test_demanda_por_nicho` |
| 4.7 Funil novo, cadência +3/+5/+7, Hoje, sessão | `test_funnel.py`, `test_api::test_hoje_e_sessao`, `test_meta_da_semana_conta_as_abordagens` |
| 4.8 Proposta e diagnóstico imprimíveis | `test_sites_outreach::test_proposta_*`, `test_diagnostico_de_uma_pagina` |
| 4.9 Cota de 30/dia no servidor | `test_providers::test_31a_requisicao_bloqueada_no_servidor`, `test_google_trava_antes_de_chamar_na_31a` |
| 4.10 Ideias do ProspectOS: checagem do site, análise da página, IA, conversa colada, lote, mapa | `test_site_check_ai.py`, `test_api::test_busca_em_lote_fila_e_cancelar`, `test_sites_outreach::test_analisar_conversa_colada` |
| Regras duras: nunca envia, "não contatar", LGPD, chaves | `test_api::test_nenhuma_rota_envia_mensagem`, `test_nao_contatar_esconde_de_tudo_e_bloqueia`, `test_excluir_de_vez_lgpd`, `test_security::test_chaves_nunca_aparecem`, `test_codigo_sem_chave_escrita` |
