# This file is auto-generated from the current state of the database. Instead
# of editing this file, please use the migrations feature of Active Record to
# incrementally modify your database, and then regenerate this schema definition.

ActiveRecord::Schema[8.1].define(version: 2026_11_15_000000) do
  create_table "notes", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "text", null: false
    t.datetime "updated_at", null: false
  end
end
