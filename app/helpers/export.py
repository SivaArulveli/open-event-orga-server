import icalendar
import pytz
from flask import url_for
from icalendar import Calendar
from pentabarf.Event import Event
from pentabarf.Day import Day
from pentabarf.Person import Person
from pentabarf.Room import Room
from sqlalchemy import DATE
from sqlalchemy import asc
from sqlalchemy import cast
from sqlalchemy import func

from app.settings import get_settings
from app.models.event import Event as EventModel
from xml.etree.ElementTree import Element, SubElement, Comment, tostring

from app import db
from app.models.session import Session

from app.helpers.data_getter import DataGetter
from pentabarf.Conference import Conference


def format_timedelta(td):
    hours, remainder = divmod(td.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    hours, minutes, seconds = int(hours), int(minutes), int(seconds)
    if hours < 10:
        hours = '0%s' % int(hours)
    if minutes < 10:
        minutes = '0%s' % minutes
    if seconds < 10:
        seconds = '0%s' % seconds
    return '%s:%s' % (hours, minutes)


class ExportHelper:

    def __init__(self):
        pass

    @staticmethod
    def export_as_pentabarf(event_id):
        event = DataGetter.get_event(event_id)
        diff = (event.end_time - event.start_time)

        tz = event.timezone or 'UTC'
        tz = pytz.timezone(tz)

        conference = Conference(title=event.name, start=tz.localize(event.start_time), end=tz.localize(event.end_time),
                                days=diff.days if diff.days > 0 else 1,
                                day_change="00:00", timeslot_duration="00:15")
        dates = (db.session.query(cast(Session.start_time, DATE))
                 .filter_by(event_id=event_id)
                 .filter_by(state='accepted')
                 .filter(Session.in_trash is not True)
                 .order_by(asc(Session.start_time)).distinct().all())

        for date in dates:
            date = date[0]
            day = Day(date=date)
            microlocation_ids = list(db.session.query(Session.microlocation_id)
                                     .filter(func.date(Session.start_time) == date)
                                     .filter_by(state='accepted')
                                     .filter(Session.in_trash is not True)
                                     .order_by(asc(Session.microlocation_id)).distinct())
            for microlocation_id in microlocation_ids:
                microlocation_id = microlocation_id[0]
                microlocation = DataGetter.get_microlocation(microlocation_id)
                sessions = Session.query.filter_by(microlocation_id=microlocation_id) \
                    .filter(func.date(Session.start_time) == date) \
                    .filter_by(state='accepted')\
                    .filter(Session.in_trash is not True)\
                    .order_by(asc(Session.start_time)).all()

                room = Room(name=microlocation.name)
                for session in sessions:

                    session_event = Event(id=session.id,
                                          date=tz.localize(session.start_time),
                                          start=tz.localize(session.start_time).strftime("%H:%M"),
                                          duration=format_timedelta(session.end_time - session.start_time),
                                          track=session.track.name,
                                          abstract=session.short_abstract,
                                          title=session.title,
                                          type='Talk',
                                          description=session.long_abstract,
                                          conf_url=url_for('event_detail.display_event_detail_home',
                                                           identifier=event.identifier),
                                          full_conf_url=url_for('event_detail.display_event_detail_home',
                                                                identifier=event.identifier, _external=True),
                                          released="True" if event.schedule_published_on else "False")

                    for speaker in session.speakers:
                        person = Person(id=speaker.id, name=speaker.name)
                        session_event.add_person(person)

                    room.add_event(session_event)
                day.add_room(room)
            conference.add_day(day)

        return conference.generate("Generated by " + get_settings()['app_name'])

    @staticmethod
    def export_as_ical(event_id):
        """Takes an event id and returns the event in iCal format"""

        event = EventModel.query.get(event_id)

        cal = Calendar()
        cal.add('prodid', '-//fossasia//open-event//EN')
        cal.add('version', '2.0')
        cal.add('x-wr-caldesc', event.name)
        cal.add('x-wr-calname', "Schedule for sessions at " + event.name)

        tz = event.timezone or 'UTC'
        tz = pytz.timezone(tz)

        sessions = Session.query\
            .filter_by(event_id=event_id) \
            .filter_by(state='accepted') \
            .filter(Session.in_trash is not True) \
            .order_by(asc(Session.start_time)).all()

        for session in sessions:

            if session and session.start_time and session.end_time:
                event_component = icalendar.Event()
                event_component.add('summary', session.title)
                event_component.add('geo', (event.latitude, event.longitude))
                event_component.add('location', session.microlocation.name or '' + " " + event.location_name)
                event_component.add('dtstart', tz.localize(session.start_time))
                event_component.add('dtend', tz.localize(session.end_time))
                event_component.add('email', event.email)
                event_component.add('description', session.short_abstract)
                event_component.add('url', url_for('event_detail.display_event_detail_home',
                                                   identifier=event.identifier, _external=True))

                attendees = []
                for speaker in session.speakers:
                    attendees.append(speaker.name)
                    event_component.add('attendee', attendees)

                cal.add_component(event_component)

        return cal.to_ical()

    @staticmethod
    def export_as_xcal(event_id):
        event = DataGetter.get_event(event_id)

        tz = event.timezone or 'UTC'
        tz = pytz.timezone(tz)

        i_calendar_node = Element('iCalendar')
        i_calendar_node.set('xmlns:xCal', 'urn:ietf:params:xml:ns:xcal')
        v_calendar_node = SubElement(i_calendar_node, 'vcalendar')
        version_node = SubElement(v_calendar_node, 'version')
        version_node.text = '2.0'
        prod_id_node = SubElement(v_calendar_node, 'prodid')
        prod_id_node.text = '-//fossasia//open-event//EN'
        cal_desc_node = SubElement(v_calendar_node, 'x-wr-caldesc')
        cal_desc_node.text = event.name
        cal_name_node = SubElement(v_calendar_node, 'x-wr-calname')
        cal_name_node.text = "Schedule for sessions at " + event.name

        sessions = Session.query\
            .filter_by(event_id=event_id) \
            .filter_by(state='accepted') \
            .filter(Session.in_trash is not True) \
            .order_by(asc(Session.start_time)).all()

        for session in sessions:

            if session and session.start_time and session.end_time:

                v_event_node = SubElement(v_calendar_node, 'vevent')

                method_node = SubElement(v_event_node, 'method')
                method_node.text = 'PUBLISH'

                uid_node = SubElement(v_event_node, 'uid')
                uid_node.text = str(session.id)

                dtstart_node = SubElement(v_event_node, 'dtstart')
                dtstart_node.text = tz.localize(session.start_time).isoformat()

                dtend_node = SubElement(v_event_node, 'dtend')
                dtend_node.text = tz.localize(session.end_time).isoformat()

                duration_node = SubElement(v_event_node, 'duration')
                duration_node.text = format_timedelta(session.end_time - session.start_time) + "00:00"

                summary_node = SubElement(v_event_node, 'summary')
                summary_node.text = session.title

                description_node = SubElement(v_event_node, 'description')
                description_node.text = session.short_abstract or 'N/A'

                class_node = SubElement(v_event_node, 'class')
                class_node.text = 'PUBLIC'

                status_node = SubElement(v_event_node, 'status')
                status_node.text = 'CONFIRMED'

                categories_node = SubElement(v_event_node, 'categories')
                categories_node.text = session.session_type.name if session.session_type else ''

                url_node = SubElement(v_event_node, 'url')
                url_node.text = url_for('event_detail.display_event_detail_home',
                                        identifier=event.identifier, _external=True)

                location_node = SubElement(v_event_node, 'location')
                location_node.text = session.microlocation.name

                for speaker in session.speakers:
                    attendee_node = SubElement(v_event_node, 'attendee')
                    attendee_node.text = speaker.name

        return tostring(i_calendar_node)
