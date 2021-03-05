''' testing models '''
from unittest.mock import patch
from io import BytesIO
import pathlib

from PIL import Image
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from bookwyrm import models, settings


@patch('bookwyrm.models.Status.broadcast')
class Status(TestCase):
    ''' lotta types of statuses '''
    def setUp(self):
        ''' useful things for creating a status '''
        self.user = models.User.objects.create_user(
            'mouse', 'mouse@mouse.mouse', 'mouseword',
            local=True, localname='mouse')
        self.book = models.Edition.objects.create(title='Test Edition')

        image_file = pathlib.Path(__file__).parent.joinpath(
            '../../static/images/default_avi.jpg')
        image = Image.open(image_file)
        output = BytesIO()
        with patch('bookwyrm.models.Status.broadcast'):
            image.save(output, format=image.format)
            self.book.cover.save(
                'test.jpg',
                ContentFile(output.getvalue())
            )

    def test_status_generated_fields(self, _):
        ''' setting remote id '''
        status = models.Status.objects.create(content='bleh', user=self.user)
        expected_id = 'https://%s/user/mouse/status/%d' % \
                (settings.DOMAIN, status.id)
        self.assertEqual(status.remote_id, expected_id)
        self.assertEqual(status.privacy, 'public')

    def test_replies(self, _):
        ''' get a list of replies '''
        parent = models.Status.objects.create(content='hi', user=self.user)
        child = models.Status.objects.create(
            content='hello', reply_parent=parent, user=self.user)
        models.Review.objects.create(
            content='hey', reply_parent=parent, user=self.user, book=self.book)
        models.Status.objects.create(
            content='hi hello', reply_parent=child, user=self.user)

        replies = models.Status.replies(parent)
        self.assertEqual(replies.count(), 2)
        self.assertEqual(replies.first(), child)
        # should select subclasses
        self.assertIsInstance(replies.last(), models.Review)

    def test_status_type(self, _):
        ''' class name '''
        self.assertEqual(models.Status().status_type, 'Note')
        self.assertEqual(models.Review().status_type, 'Review')
        self.assertEqual(models.Quotation().status_type, 'Quotation')
        self.assertEqual(models.Comment().status_type, 'Comment')
        self.assertEqual(models.Boost().status_type, 'Announce')

    def test_boostable(self, _):
        ''' can a status be boosted, based on privacy '''
        self.assertTrue(models.Status(privacy='public').boostable)
        self.assertTrue(models.Status(privacy='unlisted').boostable)
        self.assertFalse(models.Status(privacy='followers').boostable)
        self.assertFalse(models.Status(privacy='direct').boostable)

    def test_to_replies(self, _):
        ''' activitypub replies collection '''
        parent = models.Status.objects.create(content='hi', user=self.user)
        child = models.Status.objects.create(
            content='hello', reply_parent=parent, user=self.user)
        models.Review.objects.create(
            content='hey', reply_parent=parent, user=self.user, book=self.book)
        models.Status.objects.create(
            content='hi hello', reply_parent=child, user=self.user)

        replies = parent.to_replies()
        self.assertEqual(replies['id'], '%s/replies' % parent.remote_id)
        self.assertEqual(replies['totalItems'], 2)

    def test_status_to_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.Status.objects.create(
            content='test content', user=self.user)
        activity = status.to_activity()
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'Note')
        self.assertEqual(activity['content'], 'test content')
        self.assertEqual(activity['sensitive'], False)

    def test_status_to_activity_tombstone(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.Status.objects.create(
            content='test content', user=self.user,
            deleted=True, deleted_date=timezone.now())
        activity = status.to_activity()
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'Tombstone')
        self.assertFalse(hasattr(activity, 'content'))

    def test_status_to_pure_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.Status.objects.create(
            content='test content', user=self.user)
        activity = status.to_activity(pure=True)
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'Note')
        self.assertEqual(activity['content'], 'test content')
        self.assertEqual(activity['sensitive'], False)
        self.assertEqual(activity['attachment'], [])

    def test_generated_note_to_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.GeneratedNote.objects.create(
            content='test content', user=self.user)
        status.mention_books.set([self.book])
        status.mention_users.set([self.user])
        activity = status.to_activity()
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'GeneratedNote')
        self.assertEqual(activity['content'], 'test content')
        self.assertEqual(activity['sensitive'], False)
        self.assertEqual(len(activity['tag']), 2)

    def test_generated_note_to_pure_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.GeneratedNote.objects.create(
            content='test content', user=self.user)
        status.mention_books.set([self.book])
        status.mention_users.set([self.user])
        activity = status.to_activity(pure=True)
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(
            activity['content'],
            'mouse test content <a href="%s">"Test Edition"</a>' % \
                self.book.remote_id)
        self.assertEqual(len(activity['tag']), 2)
        self.assertEqual(activity['type'], 'Note')
        self.assertEqual(activity['sensitive'], False)
        self.assertIsInstance(activity['attachment'], list)
        self.assertEqual(activity['attachment'][0].type, 'Image')
        self.assertEqual(activity['attachment'][0].url, 'https://%s%s' % \
                (settings.DOMAIN, self.book.cover.url))
        self.assertEqual(
            activity['attachment'][0].name, 'Test Edition cover')

    def test_comment_to_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.Comment.objects.create(
            content='test content', user=self.user, book=self.book)
        activity = status.to_activity()
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'Comment')
        self.assertEqual(activity['content'], 'test content')
        self.assertEqual(activity['inReplyToBook'], self.book.remote_id)

    def test_comment_to_pure_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.Comment.objects.create(
            content='test content', user=self.user, book=self.book)
        activity = status.to_activity(pure=True)
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'Note')
        self.assertEqual(
            activity['content'],
            'test content<p>(comment on <a href="%s">"Test Edition"</a>)</p>' %
            self.book.remote_id)
        self.assertEqual(activity['attachment'][0].type, 'Image')
        self.assertEqual(activity['attachment'][0].url, 'https://%s%s' % \
                (settings.DOMAIN, self.book.cover.url))
        self.assertEqual(
            activity['attachment'][0].name, 'Test Edition cover')

    def test_quotation_to_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.Quotation.objects.create(
            quote='a sickening sense', content='test content',
            user=self.user, book=self.book)
        activity = status.to_activity()
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'Quotation')
        self.assertEqual(activity['quote'], 'a sickening sense')
        self.assertEqual(activity['content'], 'test content')
        self.assertEqual(activity['inReplyToBook'], self.book.remote_id)

    def test_quotation_to_pure_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.Quotation.objects.create(
            quote='a sickening sense', content='test content',
            user=self.user, book=self.book)
        activity = status.to_activity(pure=True)
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'Note')
        self.assertEqual(
            activity['content'],
            'a sickening sense <p>-- <a href="%s">"Test Edition"</a></p>' \
                    'test content' % self.book.remote_id)
        self.assertEqual(activity['attachment'][0].type, 'Image')
        self.assertEqual(activity['attachment'][0].url, 'https://%s%s' % \
                (settings.DOMAIN, self.book.cover.url))
        self.assertEqual(
            activity['attachment'][0].name, 'Test Edition cover')

    def test_review_to_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.Review.objects.create(
            name='Review name', content='test content', rating=3,
            user=self.user, book=self.book)
        activity = status.to_activity()
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'Review')
        self.assertEqual(activity['rating'], 3)
        self.assertEqual(activity['name'], 'Review name')
        self.assertEqual(activity['content'], 'test content')
        self.assertEqual(activity['inReplyToBook'], self.book.remote_id)

    def test_review_to_pure_activity(self, _):
        ''' subclass of the base model version with a "pure" serializer '''
        status = models.Review.objects.create(
            name='Review name', content='test content', rating=3,
            user=self.user, book=self.book)
        activity = status.to_activity(pure=True)
        self.assertEqual(activity['id'], status.remote_id)
        self.assertEqual(activity['type'], 'Article')
        self.assertEqual(
            activity['name'], 'Review of "%s" (3 stars): Review name' \
                % self.book.title)
        self.assertEqual(activity['content'], 'test content')
        self.assertEqual(activity['attachment'][0].type, 'Image')
        self.assertEqual(activity['attachment'][0].url, 'https://%s%s' % \
                (settings.DOMAIN, self.book.cover.url))
        self.assertEqual(
            activity['attachment'][0].name, 'Test Edition cover')

    def test_favorite(self, _):
        ''' fav a status '''
        real_broadcast = models.Favorite.broadcast
        def fav_broadcast_mock(_, activity, user):
            ''' ok '''
            self.assertEqual(user.remote_id, self.user.remote_id)
            self.assertEqual(activity['type'], 'Like')
        models.Favorite.broadcast = fav_broadcast_mock

        status = models.Status.objects.create(
            content='test content', user=self.user)
        fav = models.Favorite.objects.create(status=status, user=self.user)

        # can't fav a status twice
        with self.assertRaises(IntegrityError):
            models.Favorite.objects.create(status=status, user=self.user)

        activity = fav.to_activity()
        self.assertEqual(activity['type'], 'Like')
        self.assertEqual(activity['actor'], self.user.remote_id)
        self.assertEqual(activity['object'], status.remote_id)
        models.Favorite.broadcast = real_broadcast

    def test_boost(self, _):
        ''' boosting, this one's a bit fussy '''
        status = models.Status.objects.create(
            content='test content', user=self.user)
        boost = models.Boost.objects.create(
            boosted_status=status, user=self.user)
        activity = boost.to_activity()
        self.assertEqual(activity['actor'], self.user.remote_id)
        self.assertEqual(activity['object'], status.remote_id)
        self.assertEqual(activity['type'], 'Announce')
        self.assertEqual(activity, boost.to_activity(pure=True))

    def test_notification(self, _):
        ''' a simple model '''
        notification = models.Notification.objects.create(
            user=self.user, notification_type='FAVORITE')
        self.assertFalse(notification.read)

        with self.assertRaises(IntegrityError):
            models.Notification.objects.create(
                user=self.user, notification_type='GLORB')


    def test_create_broadcast(self, broadcast_mock):
        ''' should send out two verions of a status on create '''
        models.Comment.objects.create(
            content='hi', user=self.user, book=self.book)
        self.assertEqual(broadcast_mock.call_count, 2)
        pure_call = broadcast_mock.call_args_list[0]
        bw_call = broadcast_mock.call_args_list[1]

        self.assertEqual(pure_call[1]['software'], 'other')
        args = pure_call[0][0]
        self.assertEqual(args['type'], 'Create')
        self.assertEqual(args['object']['type'], 'Note')
        self.assertTrue('content' in args['object'])


        self.assertEqual(bw_call[1]['software'], 'bookwyrm')
        args = bw_call[0][0]
        self.assertEqual(args['type'], 'Create')
        self.assertEqual(args['object']['type'], 'Comment')
