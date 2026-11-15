Rails.application.routes.draw do
  get "up" => "rails/health#show", as: :rails_health_check

  resources :notes, only: %i[index create]
  root "notes#index"
end
