require "test_helper"

class NotesControllerTest < ActionDispatch::IntegrationTest
  test "lists notes" do
    get notes_url
    assert_response :success
    assert_select "li", text: "Buy oat milk"
  end

  test "adds a note" do
    assert_difference("Note.count") do
      post notes_url, params: { note: { text: "Ship it" } }
    end
    assert_redirected_to notes_url
  end

  test "rejects an empty note" do
    post notes_url, params: { note: { text: "" } }
    assert_response :unprocessable_content
  end
end
