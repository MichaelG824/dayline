class NotesController < ApplicationController
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
