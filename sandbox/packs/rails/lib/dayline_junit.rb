# frozen_string_literal: true

# Writes a JUnit XML report to $DAYLINE_JUNIT so the Dayline runner reads
# Minitest results the same way for every pack. The pack's test commands
# preload it (`ruby -r/opt/pack/lib/dayline_junit.rb bin/rails test`), so it
# works whatever the project's test_helper does. Minitest 6 no longer finds
# plugins on its own, hence the explicit registration.
require "minitest"

Minitest.extensions << "dayline_junit"

module Minitest
  def self.plugin_dayline_junit_init(_options)
    path = ENV["DAYLINE_JUNIT"]
    reporter << DaylineJUnitReporter.new(path) if path && !path.empty?
  end

  class DaylineJUnitReporter < AbstractReporter
    def initialize(path)
      super()
      @path = path
      @results = []
    end

    def record(result)
      @results << result
    end

    def report
      by_class = @results.group_by(&:klass)
      xml = +%(<?xml version="1.0" encoding="UTF-8"?>\n<testsuites>\n)
      by_class.each do |klass, results|
        failures = results.count { |r| r.failure && !r.skipped? && !r.error? }
        errors = results.count(&:error?)
        skipped = results.count(&:skipped?)
        time = results.sum(&:time)
        xml << "<testsuite name=\"#{esc(klass)}\" tests=\"#{results.size}\" " \
               "failures=\"#{failures}\" errors=\"#{errors}\" skipped=\"#{skipped}\" " \
               "time=\"#{format("%.4f", time)}\">\n"
        results.each { |r| xml << testcase(r) }
        xml << "</testsuite>\n"
      end
      xml << "</testsuites>\n"
      File.write(@path, xml)
    end

    private

    def testcase(result)
      head = "<testcase classname=\"#{esc(result.klass)}\" name=\"#{esc(result.name)}\" " \
             "time=\"#{format("%.4f", result.time)}\""
      failure = result.failure
      return "#{head}/>\n" unless failure

      tag = if result.skipped? then "skipped" elsif result.error? then "error" else "failure" end
      # An error's message already ends with its (filtered) backtrace; a
      # failed assertion's does not, so say where it failed.
      message = failure.message.to_s
      body = tag == "failure" ? "#{result.source_location.join(":")}\n#{message}" : message
      "#{head}>\n<#{tag} message=\"#{esc(message.lines.first.to_s.strip)}\">" \
        "#{esc(body)}</#{tag}>\n</testcase>\n"
    end

    def esc(text)
      text.to_s.encode("UTF-8", invalid: :replace, undef: :replace)
          .gsub(/[^\t\n\r\u0020-\uD7FF\uE000-\uFFFD]/, "") # Characters XML cannot hold.
          .gsub("&", "&amp;").gsub("<", "&lt;").gsub(">", "&gt;").gsub('"', "&quot;")
    end
  end
end
