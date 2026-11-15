require "test_helper"

class NoteTest < ActiveSupport::TestCase
  test "strips whitespace and requires text" do
    assert_equal "Hi", Note.create!(text: "  Hi  ").text
    assert_not Note.new(text: "   ").valid?
  end
end
