import json
import logging
from django.apps import apps
from django.db.models import Exists, OuterRef
from super_csv.csv_processor import CSVProcessor, DeferrableMixin
from bulk_grades.api import get_scores

log = logging.getLogger(__name__)


def _get_enrollments(course_id, active_only=False, excluded_course_roles=None):
    """
    Return iterator of enrollment dictionaries.
    {
        'user': user object
        'user_id': user id
        'username': username
        'full_name': user's full name
        'enrolled': bool
    }
    """
    enrollments = apps.get_model('student', 'CourseEnrollment').objects.filter(course_id=course_id).select_related(
        'user')
    if active_only:
        enrollments = enrollments.filter(is_active=True)
    if excluded_course_roles:
        course_access_role_filters = dict(
            user=OuterRef('user'),
            course_id=course_id
        )
        if 'all' not in excluded_course_roles:
            course_access_role_filters['role__in'] = excluded_course_roles
        enrollments = enrollments.annotate(has_excluded_course_role=Exists(
            apps.get_model('student', 'CourseAccessRole').objects.filter(**course_access_role_filters)
        ))
        enrollments = enrollments.exclude(has_excluded_course_role=True)

    for enrollment in enrollments:
        enrollment_dict = {
            'user': enrollment.user,
            'user_id': enrollment.user.id,
            'username': enrollment.user.username,
            'full_name': enrollment.user.profile.name,
            'enrolled': enrollment.is_active,
            'track': enrollment.mode,
        }
        yield enrollment_dict


class FeedbackCSVProcessor(DeferrableMixin, CSVProcessor):
    """
    CSV Processor for file format defined for Feedback.
    """

    columns = ['username', 'full_name', 'title', 'date_last_feedback',
               'vote', 'feedback']

    def __init__(self, **kwargs):
        """
        Create a ScoreCSVProcessor.
        """
        self.max_points = 1
        self.user_id = None
        self.display_name = ''
        self.location = None
        self.prompt = {}
        super().__init__(**kwargs)
        self._users_seen = set()

    def get_unique_path(self):
        """
        Return a unique id for CSVOperations.
        """
        return self.block_id

    def get_rows_to_export(self):
        """
        Return iterator of rows for file export.
        """
        my_name = self.display_name

        students = get_scores(self.location)
        enrollments = _get_enrollments(self.location.course_key)
        for enrollment in enrollments:
            row = {
                'title': my_name,
                'date_last_feedback': None,
                'username': enrollment['username'],
                'full_name': enrollment['full_name'],
            }
            score = students.get(enrollment['user_id'], None)

            if score and score.get('state'):
                try:
                    state = json.loads(score['state'])
                    vote_idx = state.get('user_vote', -1)
                    if self.prompt and vote_idx >= 0:
                        # convert vote index to text
                        row['vote'] = self.prompt['scale_text'][vote_idx]
                    row['feedback'] = state.get('user_freeform', '')
                    row['date_last_feedback'] = score['modified'].strftime('%Y-%m-%d %H:%M')
                except Exception as e:
                    log.info("Meets exception when prepare data {}: {}".format(score, e))
                    continue
            yield row
