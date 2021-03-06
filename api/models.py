from datetime import datetime

from django.db import models, transaction
from django.contrib.auth.models import User
from django.db.models.signals import post_save


class UserProfile(models.Model):
    user = models.OneToOneField(User)
    difficulty = models.IntegerField(
        choices=(
            (0, 'Very Easy'),
            (1, 'Easy'),
            (2, 'Medium'),
            (3, 'Hard'),
            (4, 'Very Hard'),
        ), default=2)

    @property
    def owner(self):
        return self.user


def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

post_save.connect(create_user_profile, sender=User)


class Problem(models.Model):
    problemId = models.IntegerField(primary_key=True)
    problemName = models.CharField(max_length=256, db_index=True)
    problemStatement = models.TextField()

    matchName = models.CharField(max_length=128, db_index=True)

    points = models.IntegerField(db_index=True)
    tags = models.CharField(max_length=512, db_index=True)

    date = models.DateField(db_index=True)

    users = models.ManyToManyField(
        User,
        through='ProblemStar',
        through_fields=('problem', 'user'),
        related_name='starred_problems',
    )

    def __unicode__(self):
        return u'Problem: [#%d] %s' % (self.problemId, self.problemName)


class ProblemStar(models.Model):
    problem = models.ForeignKey(Problem, related_name='stars')
    user = models.ForeignKey(User, related_name='stars')
    datetime = models.DateTimeField(auto_now_add=True, db_index=True)

    def __unicode__(self):
        return u'Star: #%d <-> %s' % (self.problem.problemId, self.user.username)

    class Meta:
        ordering = ('-datetime', )
        unique_together = ('problem', 'user')


class ProblemSheet(models.Model):
    number = models.IntegerField(db_index=True)
    user = models.ForeignKey(User, related_name="sheets")
    date = models.DateField(auto_now_add=True)

    @property
    def owner(self):
        return self.user

    @property
    def is_last(self):
        return self.user.sheets.last().id == self.id

    @property
    def difficulty_range(self):
        difficulty_ranges = (
            (0, 200),
            (200, 400),
            (400, 600),
            (600, 800),
            (800, 1000)
        )
        difficulty = self.user.userprofile.difficulty
        return difficulty_ranges[difficulty]

    @classmethod
    @transaction.atomic
    def add(cls, user):
        return cls.objects.create(
            number=user.sheets.count() + 1,
            user=user
        )

    @transaction.atomic
    def auto_assign_problems(self):
        if self.problems.count() > 0: return

        overdues = ProblemAssignment.objects.filter(
            sheet__user=self.user,
            type='new',
            done=False
        ).prefetch_related('originProblem').all()

        for overdue in overdues:
            ProblemAssignment.assign_problem(overdue.originProblem, self, 'overdue')

        reviews = ProblemAssignment.objects.filter(
            sheet__user=self.user,
            type='new',
            done=True,
        ).order_by('?').all()[:2]

        for review in reviews:
            ProblemAssignment.assign_problem(review.originProblem, self, 'review')

        total = len(overdues) + len(reviews)
        if total < 12:
            allassigns = ProblemAssignment.objects.filter(
                sheet__user=self.user,
                type='new',
            ).values_list('originProblem', flat=True)
            low, high = self.difficulty_range
            newproblems = Problem.objects.filter(
                points__gte=low,
                points__lte=high,
            ).exclude(
                problemId__in=allassigns,
            ).order_by('?').all()[:12 - total]
            for problem in newproblems:
                ProblemAssignment.assign_problem(problem, self)

    def __unicode__(self):
        return u'Sheet: #%d for %s' % (self.number, self.user.username)


class ProblemAssignment(models.Model):
    sheet = models.ForeignKey(ProblemSheet, related_name="problems")
    originProblem = models.ForeignKey(Problem, related_name="assignments")
    problemName = models.CharField(max_length=128)
    points = models.IntegerField()
    tags = models.CharField(max_length=128)
    date = models.DateField()
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    type = models.CharField(max_length=10, default='new', choices=(
        ('new', 'Unsolved problem'),
        ('overdue', 'Overdue problem'),
        ('review', 'Problem to review'),
    ))

    @property
    def owner(self):
        return self.sheet.user

    @classmethod
    def assign_problem(cls, problem, sheet, type_='new'):
        return cls.objects.create(
            sheet=sheet,
            originProblem=problem,
            problemName=problem.problemName,
            points=problem.points,
            tags=problem.tags,
            date=problem.date,
            type=type_
        )

    @transaction.atomic
    def done_problem(self):
        ProblemAssignment.objects.filter(
            sheet__user=self.sheet.user,
            originProblem=self.originProblem,
        ).update(done=True)
        ProblemAssignment.objects.filter(
            sheet__user=self.sheet.user,
            originProblem=self.originProblem,
            done_at=None,
        ).update(done_at=datetime.now())


class ProblemComment(models.Model):
    user = models.ForeignKey(User, related_name="users")
    problem = models.ForeignKey(Problem, related_name="comments")
    content = models.TextField()
    datetime = models.DateTimeField(auto_now_add=True, auto_now=True, db_index=True)

    @property
    def owner(self):
        return self.user

    def __unicode__(self):
        return u'Comment: %s on [#%d]' % (self.user.username, self.problem.id)

    class Meta:
        ordering = ('-datetime', )
