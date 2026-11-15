class Note < ApplicationRecord
  normalizes :text, with: ->(text) { text.strip }
  validates :text, presence: true, length: { maximum: 200 }
end
