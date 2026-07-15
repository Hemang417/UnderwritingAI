from app.adapters.maha_rera_live import (
    build_list_page_params,
    map_address,
    map_general_details,
    map_promoter_details,
    parse_list_page,
)

_SAMPLE_CARD_HTML = """
<div class="row shadow p-3 mb-5 bg-body rounded">
  <div class="col-xl-4">
    <h4 class="title4">Lodha Park</h4>
    <p class="p-0"># P51900001234</p>
    <p class="darkBlue bold">Lodha Group</p>
  </div>
  <div class="col-xl-6">
    <div class="greyColor">District</div>
    <p>Mumbai City</p>
    <div class="greyColor">Last Modified</div>
    <p>01-07-2026</p>
  </div>
  <div class="col-xl-2">
    <a class="click-projectmodal viewLink" href="/public/project/view/100">View</a>
  </div>
</div>
"""

_LIST_PAGE_HTML = f"""
<html><body>
{_SAMPLE_CARD_HTML}
</body></html>
"""

_MALFORMED_CARD_HTML = """
<div class="row shadow p-3 mb-5 bg-body rounded">
  <div class="col-xl-4">
    <h4 class="title4">Missing Registration Number Project</h4>
  </div>
</div>
"""


def test_parse_list_page_extracts_a_well_formed_card():
    stubs = parse_list_page(_LIST_PAGE_HTML)
    assert len(stubs) == 1
    stub = stubs[0]
    assert stub["registration_number"] == "P51900001234"
    assert stub["project_name"] == "Lodha Park"
    assert stub["developer_name"] == "Lodha Group"
    assert stub["district"] == "Mumbai City"
    assert stub["project_id"] == "100"


def test_parse_list_page_skips_cards_missing_registration_number_or_project_id():
    stubs = parse_list_page(f"<html><body>{_MALFORMED_CARD_HTML}</body></html>")
    assert stubs == []


def test_parse_list_page_returns_empty_list_for_no_cards():
    assert parse_list_page("<html><body>No results found</body></html>") == []


def test_parse_list_page_handles_multiple_cards():
    html = f"<html><body>{_SAMPLE_CARD_HTML}{_SAMPLE_CARD_HTML}</body></html>"
    stubs = parse_list_page(html)
    assert len(stubs) == 2


def test_build_list_page_params_includes_project_name_and_page():
    params = build_list_page_params(3, "Lodha Park")
    assert params["project_name"] == "Lodha Park"
    assert params["page"] == 3
    assert params["project_district"] == 0
    assert params["project_state"] == 27


def test_build_list_page_params_defaults_to_empty_name():
    params = build_list_page_params(1)
    assert params["project_name"] == ""


def test_map_general_details_translates_maharera_typo_field_names():
    response_object = {
        "projectRegistartionNo": "P51900001234",
        "projectName": "Lodha Park",
        "projectStatusName": "Ongoing Project",
        "projectProposeComplitionDate": "2027-12-31",
        "userProfileId": "profile-123",
    }
    result = map_general_details(response_object)
    assert result["registration_number"] == "P51900001234"
    assert result["project_name"] == "Lodha Park"
    assert result["status_name"] == "Ongoing Project"
    assert result["proposed_completion_date"] == "2027-12-31"
    assert result["promoter_profile_id"] == "profile-123"


def test_map_general_details_handles_missing_fields_as_none():
    result = map_general_details({})
    assert all(v is None for v in result.values())


def test_map_general_details_handles_none_response():
    result = map_general_details(None)
    assert all(v is None for v in result.values())


def test_map_promoter_details_extracts_nested_promoter_name():
    response_object = {"promoterDetails": {"promoterName": "Lodha Group"}}
    result = map_promoter_details(response_object)
    assert result["developer_name"] == "Lodha Group"


def test_map_promoter_details_handles_missing_promoter_details():
    assert map_promoter_details({})["developer_name"] is None
    assert map_promoter_details(None)["developer_name"] is None


def test_map_address_handles_list_shaped_response():
    response_object = [{"districtName": "Mumbai City", "talukaName": "Andheri", "stateName": "Maharashtra"}]
    result = map_address(response_object)
    assert result["district"] == "Mumbai City"
    assert result["taluka"] == "Andheri"
    assert result["state"] == "Maharashtra"


def test_map_address_handles_empty_list():
    result = map_address([])
    assert all(v is None for v in result.values())


def test_map_address_handles_dict_shaped_response():
    result = map_address({"districtName": "Pune"})
    assert result["district"] == "Pune"
