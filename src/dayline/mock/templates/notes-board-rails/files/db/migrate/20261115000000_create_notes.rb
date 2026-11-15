class CreateNotes < ActiveRecord::Migration[8.1]
  def change
    create_table :notes do |t|
      t.string :text, null: false
      t.timestamps
    end
  end
end
