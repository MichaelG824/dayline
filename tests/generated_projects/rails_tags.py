"""A generated project for the rails stack, as the model would submit it (the
``submit_project`` tool input): the scaffold's notes board, a task to add
tags (a migration, the model, the form and the list), and a change request
to filter the list by tag. A real, working project, validated end to end by
the opt-in Docker test.
"""

from __future__ import annotations

from typing import Any

README = """# Notes board

A small Rails 8 notes app backed by SQLite.
`NotesController` lists and adds notes; `Note` validates them.

The dev server starts with the sandbox (it runs `bin/rails db:prepare` first) and reloads code as you save.
Restart it from the Preview panel after changing config or adding a migration.
Run the tests with `bin/rails test` (or the Run tests button).
"""

MIGRATION = """class AddTagsToNotes < ActiveRecord::Migration[8.1]
  def change
    add_column :notes, :tags, :string, null: false, default: ""
  end
end
"""

SCHEMA = """# This file is auto-generated from the current state of the database. Instead
# of editing this file, please use the migrations feature of Active Record to
# incrementally modify your database, and then regenerate this schema definition.

ActiveRecord::Schema[8.1].define(version: 2026_11_15_000001) do
  create_table "notes", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "tags", default: "", null: false
    t.string "text", null: false
    t.datetime "updated_at", null: false
  end
end
"""

MODEL_TAGS = """class Note < ApplicationRecord
  normalizes :text, with: ->(text) { text.strip }
  normalizes :tags, with: ->(tags) { tags.split(",").map { _1.strip.downcase }.reject(&:empty?).uniq.join(",") }
  validates :text, presence: true, length: { maximum: 200 }

  def tag_list = tags.split(",")
end
"""

MODEL_FILTER = MODEL_TAGS.replace(
    "  validates :text",
    """  scope :tagged, ->(tag) { where("',' || tags || ',' LIKE ?", "%,#{sanitize_sql_like(tag)},%") }
  validates :text""",
)

CONTROLLER = """class NotesController < ApplicationController
  def index
    @notes = Note.order(created_at: :desc)
    @note = Note.new
  end

  def create
    @note = Note.new(note_params)
    if @note.save
      redirect_to notes_path, notice: "Note added."
    else
      @notes = Note.order(created_at: :desc)
      render :index, status: :unprocessable_content
    end
  end

  private

  def note_params
    params.expect(note: [:text])
  end
end
"""

CONTROLLER_TAGS = CONTROLLER.replace(
    "params.expect(note: [:text])", "params.expect(note: [:text, :tags])"
)
CONTROLLER_FILTER = CONTROLLER_TAGS.replace(
    """    @notes = Note.order(created_at: :desc)
    @note = Note.new""",
    """    @tag = params[:tag].to_s.strip.downcase.presence
    @notes = Note.order(created_at: :desc)
    @notes = @notes.tagged(@tag) if @tag
    @note = Note.new""",
)

VIEW_TAGS = """<h1>Notes board</h1>

<%= form_with model: @note do |form| %>
  <%= form.text_field :text, placeholder: "Write a note", "aria-label": "New note" %>
  <%= form.text_field :tags, placeholder: "Tags, comma separated", "aria-label": "Tags" %>
  <%= form.submit "Add" %>
<% end %>
<% @note.errors.full_messages.each do |message| %>
  <p class="error"><%= message %></p>
<% end %>

<ul>
  <% @notes.each do |note| %>
    <li><%= note.text %><% note.tag_list.each do |tag| %> <span class="tag"><%= tag %></span><% end %></li>
  <% end %>
</ul>
"""

TAGS_TEST = """require "test_helper"

class Stage1TagsTest < ActionDispatch::IntegrationTest
  test "saves normalised tags" do
    post notes_url, params: { note: { text: "Plan", tags: " Work, ideas ,work" } }
    assert_equal %w[work ideas], Note.order(:created_at).last.tag_list
  end

  test "shows tags in the list" do
    Note.create!(text: "Tagged", tags: "home")
    get notes_url
    assert_select ".tag", text: "home"
  end
end
"""

FILTER_TEST = """require "test_helper"

class Stage2FilterTest < ActionDispatch::IntegrationTest
  test "filters the list by tag" do
    Note.create!(text: "Gym", tags: "health")
    Note.create!(text: "Report", tags: "work,urgent")
    get notes_url(tag: "Work")
    assert_select "li", count: 1
    assert_select "li", text: /Report/
  end
end
"""


def submit_input() -> dict[str, Any]:
    return {
        "title": "Tagged notes (Rails)",
        "summary": "A Rails notes board: add tags, then filter the list by tag.",
        "open_path": "app/controllers/notes_controller.rb",
        "files": [{"path": "README.md", "content": README}],
        "task": {
            "title": "Tag notes",
            "prompt_md": (
                "Let a note have comma-separated tags: a Tags field on the form, tags saved "
                "trimmed, lower-cased and without duplicates, and shown on each note in the list."
            ),
            "notes_md": "Ask where normalising belongs and how they would index tags later.",
            "target_min": 25,
            "tests": [{"name": "tags_test.rb", "content": TAGS_TEST}],
            "reference": [
                {"path": "db/migrate/20261115000001_add_tags_to_notes.rb", "content": MIGRATION},
                {"path": "db/schema.rb", "content": SCHEMA},
                {"path": "app/models/note.rb", "content": MODEL_TAGS},
                {"path": "app/controllers/notes_controller.rb", "content": CONTROLLER_TAGS},
                {"path": "app/views/notes/index.html.erb", "content": VIEW_TAGS},
            ],
            "edge_cases": [
                {"id": "normalise", "title": "Normalises tags", "tests": ["saves normalised tags"]}
            ],
        },
        "change_request": {
            "title": "Filter by tag",
            "prompt_md": "Can `/notes?tag=work` show only the notes tagged work?",
            "notes_md": "Look for SQL built from params without sanitising.",
            "target_min": 20,
            "tests": [{"name": "filter_test.rb", "content": FILTER_TEST}],
            "reference": [
                {"path": "app/models/note.rb", "content": MODEL_FILTER},
                {"path": "app/controllers/notes_controller.rb", "content": CONTROLLER_FILTER},
            ],
            "edge_cases": [],
        },
        "analysis_hints": ["Did they update db/schema.rb along with the migration?"],
    }
