# This file is used by Rack-based servers to start the application.

require_relative "config/environment"

# Dayline's preview serves the app under BASE_PATH (empty when run elsewhere).
map(ENV["BASE_PATH"].to_s.empty? ? "/" : ENV["BASE_PATH"]) do
  run Rails.application
end
Rails.application.load_server
